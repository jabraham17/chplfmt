use super::token::{Pos, Token, TokenKind, Tokens, NO_MATCH};

#[derive(Debug, PartialEq, Eq)]
pub enum LexErrorKind {
    TooLarge,
    UnterminatedString,
    UnterminatedBlockComment,
    InvalidCharacter(char),
    OpaqueWhitespace,
    OpaqueToken,
    OpaqueOutside,
    Unmatched(char),
}

#[derive(Debug, PartialEq, Eq)]
pub struct LexError {
    pub offset_cp: usize,
    pub reason: LexErrorKind,
}

fn digit(byte: u8) -> bool {
    byte.is_ascii_digit()
}

fn ident_start(byte: u8) -> bool {
    byte.is_ascii_alphabetic() || byte == b'_'
}

fn ident_continue(byte: u8) -> bool {
    ident_start(byte) || digit(byte)
}

fn run(bytes: &[u8], mut at: usize, accept: impl Fn(u8) -> bool) -> usize {
    while at < bytes.len() && accept(bytes[at]) {
        at += 1;
    }
    at
}

fn digits(bytes: &[u8], at: usize, accept: impl Fn(u8) -> bool) -> Option<usize> {
    if !bytes.get(at).is_some_and(|byte| accept(*byte)) {
        return None;
    }
    Some(run(bytes, at + 1, |byte| accept(byte) || byte == b'_'))
}

fn exponent(bytes: &[u8], at: usize, marker: &[u8]) -> Option<usize> {
    if !bytes.get(at).is_some_and(|byte| marker.contains(byte)) {
        return None;
    }
    let next = at + 1 + usize::from(bytes.get(at + 1).is_some_and(|b| *b == b'+' || *b == b'-'));
    digits(bytes, next, digit)
}

fn number_end(bytes: &[u8], at: usize) -> usize {
    let mut best = at;
    if bytes[at] == b'0' {
        if bytes.get(at + 1).is_some_and(|b| b"bB".contains(b)) {
            best = best.max(digits(bytes, at + 2, |b| b"01".contains(&b)).unwrap_or(at));
        }
        if bytes.get(at + 1).is_some_and(|b| b"oO".contains(b)) {
            best = best.max(digits(bytes, at + 2, |b| b"01234567".contains(&b)).unwrap_or(at));
        }
    }
    let decimal = digits(bytes, at, digit);
    if let Some(end) = decimal {
        best = best.max(end);
        best = best.max(exponent(bytes, end, b"eE").unwrap_or(at));
        if bytes.get(end) == Some(&b'.') {
            if let Some(real) = digits(bytes, end + 1, digit) {
                best = best.max(exponent(bytes, real, b"eE").unwrap_or(real));
            }
            best = best.max(exponent(bytes, end + 1, b"eE").unwrap_or(at));
        }
    } else if bytes[at] == b'.' {
        if let Some(real) = digits(bytes, at + 1, digit) {
            best = best.max(exponent(bytes, real, b"eE").unwrap_or(real));
        }
    }
    if bytes.get(at) == Some(&b'0') && bytes.get(at + 1).is_some_and(|b| b"xX".contains(b)) {
        let hex_start = at + 2;
        let hex = digits(bytes, hex_start, |b| b.is_ascii_hexdigit());
        if let Some(end) = hex {
            best = best.max(end);
            best = best.max(exponent(bytes, end, b"pP").unwrap_or(at));
        }
        let dot = hex.unwrap_or(hex_start);
        if bytes.get(dot) == Some(&b'.') {
            if let Some(real) = digits(bytes, dot + 1, |b| b.is_ascii_hexdigit()) {
                best = best.max(exponent(bytes, real, b"pP").unwrap_or(real));
            }
            if hex.is_some() {
                best = best.max(exponent(bytes, dot + 1, b"pP").unwrap_or(at));
            }
        }
    }
    best + usize::from(bytes.get(best) == Some(&b'i'))
}

fn string_end(text: &str, quote_at: usize) -> Option<usize> {
    let bytes = text.as_bytes();
    let quote = bytes[quote_at];
    if bytes.get(quote_at..quote_at + 3) == Some(&[quote, quote, quote]) {
        return bytes[quote_at + 3..]
            .windows(3)
            .position(|window| window == [quote, quote, quote])
            .map(|index| quote_at + 6 + index);
    }
    let mut cursor = quote_at + 1;
    while cursor < bytes.len() {
        if bytes[cursor] == quote {
            return Some(cursor + 1);
        }
        if bytes[cursor] == b'\\' {
            cursor += 1;
            if cursor == bytes.len() {
                return None;
            }
        }
        cursor += text[cursor..].chars().next()?.len_utf8();
    }
    None
}

fn block_end(bytes: &[u8], at: usize) -> Option<usize> {
    let first_close = bytes[at + 2..].windows(2).position(|pair| pair == b"*/");
    let first_open = bytes[at + 2..].windows(2).position(|pair| pair == b"/*");
    if let Some(close) = first_close {
        if first_open.is_none_or(|open| open > close) {
            return Some(at + 2 + close + 2);
        }
    }
    let (mut depth, mut cursor, mut last, mut current) = (1, at + 2, 0, 0);
    while depth > 0 {
        let byte = *bytes.get(cursor)?;
        cursor += 1;
        let (previous, previous_previous) = (current, last);
        last = previous;
        current = byte;
        if previous == b'*' && byte == b'/' && previous_previous != b'/' {
            depth -= 1;
        } else if previous == b'/' && byte == b'*' {
            depth += 1;
        }
    }
    Some(cursor)
}

const PUNCT_3: &[&str] = &["**=", "&&=", "||=", "<<=", ">>=", "<=>", "..<", "..."];
const PUNCT_2: &[&str] = &[
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "=>", "..", "&&", "||", "<<", ">>", "==", "!=",
    "<=", ">=", "--", "++", "**",
];

fn scan(text: &str, at: usize, offset_cp: usize) -> Result<(TokenKind, usize), LexError> {
    let bytes = text.as_bytes();
    let byte = bytes[at];
    let next = bytes.get(at + 1).copied();
    let error = |reason| LexError { offset_cp, reason };
    if ident_start(byte) {
        let end = run(bytes, at + 1, ident_continue);
        let word = &text[at..end];
        if word == "b" && next.is_some_and(|b| b == b'"' || b == b'\'') {
            return string_end(text, end)
                .map(|end| (TokenKind::String, end))
                .ok_or_else(|| error(LexErrorKind::UnterminatedString));
        }
        if (word == "try" && bytes.get(end) == Some(&b'!'))
            || (word == "init" && bytes.get(end) == Some(&b'='))
            || (word == "reduce" && bytes.get(end) == Some(&b'='))
        {
            return Ok((
                if word == "reduce" {
                    TokenKind::Punct
                } else {
                    TokenKind::Ident
                },
                end + 1,
            ));
        }
        return Ok((TokenKind::Ident, end));
    }
    if digit(byte) || (byte == b'.' && next.is_some_and(digit)) {
        return Ok((TokenKind::Number, number_end(bytes, at)));
    }
    if byte == b'"' || byte == b'\'' {
        return string_end(text, at)
            .map(|end| (TokenKind::String, end))
            .ok_or_else(|| error(LexErrorKind::UnterminatedString));
    }
    if byte == b'/' && next == Some(b'/') {
        let newline = bytes[at..].iter().position(|b| *b == b'\n');
        return Ok((
            TokenKind::LineComment,
            newline.map_or(bytes.len(), |index| {
                let end = at + index;
                end - usize::from(end > at && bytes[end - 1] == b'\r')
            }),
        ));
    }
    if byte == b'/' && next == Some(b'*') {
        return block_end(bytes, at)
            .map(|end| (TokenKind::BlockComment, end))
            .ok_or_else(|| error(LexErrorKind::UnterminatedBlockComment));
    }
    if (byte == b'?' || byte == b'@') && next.is_some_and(ident_start) {
        return Ok((TokenKind::Ident, run(bytes, at + 2, ident_continue)));
    }
    for table in [PUNCT_3, PUNCT_2] {
        if let Some(op) = table.iter().find(|op| text[at..].starts_with(**op)) {
            return Ok((TokenKind::Punct, at + op.len()));
        }
    }
    if b"=#!&|^~<>+-*/%:;,.()[]{}?@".contains(&byte) {
        return Ok((TokenKind::Punct, at + 1));
    }
    Err(error(LexErrorKind::InvalidCharacter(
        text[at..].chars().next().unwrap(),
    )))
}

fn advance(text: &str, from: usize, to: usize, offset_cp: &mut usize, pos: &mut Pos) {
    let part = &text[from..to];
    *offset_cp += part.chars().count();
    for byte in part.bytes() {
        if byte == b'\n' {
            pos.line += 1;
            pos.col = 1;
        } else {
            pos.col += 1;
        }
    }
}

pub fn lex<'s>(text: &'s str, opaque: &[(usize, usize)]) -> Result<Tokens<'s>, LexError> {
    let bytes = text.as_bytes();
    if bytes.len() >= u32::MAX as usize {
        return Err(LexError {
            offset_cp: 0,
            reason: LexErrorKind::TooLarge,
        });
    }
    let mut toks: Vec<Token> = Vec::new();
    let mut offset_cp = 0;
    let mut pos = Pos { line: 1, col: 1 };
    let mut cursor = 0;
    let mut range_index = 0;
    loop {
        let gap_start = cursor;
        let gap_pos = pos;
        cursor = run(bytes, cursor, |b| b" \t\r\n\x0c".contains(&b));
        advance(text, gap_start, cursor, &mut offset_cp, &mut pos);
        let next_opaque = opaque.get(range_index).map_or(usize::MAX, |range| range.0);
        if next_opaque < offset_cp {
            return Err(LexError {
                offset_cp: next_opaque,
                reason: LexErrorKind::OpaqueWhitespace,
            });
        }
        if cursor == bytes.len() {
            toks.push(Token {
                kind: TokenKind::Eof,
                ws_before: cursor > gap_start,
                nl_before: pos.line - gap_pos.line,
                start_byte: cursor as u32,
                end_byte: cursor as u32,
                start_cp: offset_cp as u32,
                end_cp: offset_cp as u32,
                start: pos,
                end: pos,
                partner: NO_MATCH,
            });
            break;
        }
        let (kind, end) = if next_opaque == offset_cp {
            let range = opaque[range_index];
            range_index += 1;
            if range.1 <= offset_cp {
                return Err(LexError {
                    offset_cp: range.0,
                    reason: LexErrorKind::OpaqueOutside,
                });
            }
            let end = text[cursor..]
                .char_indices()
                .nth(range.1 - offset_cp)
                .map(|(byte, _)| cursor + byte)
                .or_else(|| {
                    (range.1 - offset_cp == text[cursor..].chars().count()).then_some(bytes.len())
                })
                .ok_or(LexError {
                    offset_cp: range.0,
                    reason: LexErrorKind::OpaqueOutside,
                })?;
            (TokenKind::Opaque, end)
        } else {
            let (kind, end) = scan(text, cursor, offset_cp)?;
            if offset_cp + text[cursor..end].chars().count() > next_opaque {
                return Err(LexError {
                    offset_cp: next_opaque,
                    reason: LexErrorKind::OpaqueToken,
                });
            }
            (kind, end)
        };
        let start = pos;
        let start_cp = offset_cp;
        advance(text, cursor, end, &mut offset_cp, &mut pos);
        toks.push(Token {
            kind,
            ws_before: cursor > gap_start,
            nl_before: start.line - gap_pos.line,
            start_byte: cursor as u32,
            end_byte: end as u32,
            start_cp: start_cp as u32,
            end_cp: offset_cp as u32,
            start,
            end: pos,
            partner: NO_MATCH,
        });
        cursor = end;
    }
    if let Some(range) = opaque.get(range_index) {
        return Err(LexError {
            offset_cp: range.0,
            reason: LexErrorKind::OpaqueOutside,
        });
    }
    let mut stack: Vec<usize> = Vec::new();
    for index in 0..toks.len() {
        let token = toks[index];
        if token.kind != TokenKind::Punct || token.end_byte != token.start_byte + 1 {
            continue;
        }
        let ch = bytes[token.start_byte as usize];
        if b"([{ ".contains(&ch) && ch != b' ' {
            stack.push(index);
        } else if b")]}".contains(&ch) {
            let opening = match ch {
                b')' => b'(',
                b']' => b'[',
                _ => b'{',
            };
            if stack
                .last()
                .is_none_or(|open| bytes[toks[*open].start_byte as usize] != opening)
            {
                return Err(LexError {
                    offset_cp: token.start_cp as usize,
                    reason: LexErrorKind::Unmatched(ch as char),
                });
            }
            let open = stack.pop().unwrap();
            toks[open].partner = index as u32;
            toks[index].partner = open as u32;
        }
    }
    if let Some(open) = stack.pop() {
        let token = toks[open];
        return Err(LexError {
            offset_cp: token.start_cp as usize,
            reason: LexErrorKind::Unmatched(bytes[token.start_byte as usize] as char),
        });
    }
    Ok(Tokens { text, toks })
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn naive_pos(text: &str) -> Pos {
        let mut pos = Pos { line: 1, col: 1 };
        for byte in text.bytes() {
            if byte == b'\n' {
                pos.line += 1;
                pos.col = 1;
            } else {
                pos.col += 1;
            }
        }
        pos
    }

    fn check_lex(text: &str) -> Result<(), TestCaseError> {
        let Ok(tokens) = lex(text, &[]) else {
            return Ok(());
        };
        let mut reconstructed = String::new();
        let mut cursor = 0;
        let mut stack = Vec::new();
        for (index, token) in tokens.toks.iter().enumerate() {
            prop_assert!(cursor <= token.start_byte as usize);
            prop_assert!(token.start_byte <= token.end_byte);
            let gap = &text[cursor..token.start_byte as usize];
            prop_assert!(gap.bytes().all(|byte| b" \t\r\n\x0c".contains(&byte)));
            prop_assert_eq!(token.ws_before, !gap.is_empty());
            prop_assert_eq!(
                token.nl_before,
                gap.bytes().filter(|byte| *byte == b'\n').count() as u32
            );
            reconstructed.push_str(gap);
            reconstructed.push_str(tokens.text(index));
            cursor = token.end_byte as usize;
            prop_assert_eq!(
                token.start_cp as usize,
                text[..token.start_byte as usize].chars().count()
            );
            prop_assert_eq!(token.end_cp as usize, text[..cursor].chars().count());
            prop_assert_eq!(token.start, naive_pos(&text[..token.start_byte as usize]));
            prop_assert_eq!(token.end, naive_pos(&text[..cursor]));
            match tokens.text(index) {
                "(" | "[" | "{" if token.kind == TokenKind::Punct => stack.push(index),
                ")" | "]" | "}" if token.kind == TokenKind::Punct => {
                    prop_assert!(!stack.is_empty());
                    let open = stack.pop().unwrap();
                    let expected = match tokens.text(index) {
                        ")" => "(",
                        "]" => "[",
                        _ => "{",
                    };
                    prop_assert_eq!(tokens.text(open), expected);
                    prop_assert_eq!(tokens.toks[open].partner, index as u32);
                    prop_assert_eq!(token.partner, open as u32);
                }
                _ => prop_assert_eq!(token.partner, NO_MATCH),
            }
        }
        prop_assert!(stack.is_empty());
        prop_assert_eq!(cursor, text.len());
        prop_assert_eq!(reconstructed, text);
        prop_assert_eq!(tokens.toks.last().unwrap().kind, TokenKind::Eof);
        Ok(())
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(128))]

        #[test]
        fn random_utf8_reconstructs_input(text in ".{0,160}") {
            check_lex(&text)?;
        }

        #[test]
        fn random_bytes_never_panic(bytes in proptest::collection::vec(any::<u8>(), 0..160)) {
            let text = String::from_utf8_lossy(&bytes);
            check_lex(&text)?;
        }

        #[test]
        fn random_chapel_characters(text in "[a-zA-Z0-9_{}()\\[\\] ;+*/='\"\\n\\t]{0,160}") {
            check_lex(&text)?;
        }

        #[test]
        fn valid_unicode_tokens(
            contents in "[a-zA-Z0-9 中😀]{0,32}",
            identifiers in proptest::collection::vec("[a-z_][a-z0-9_]{0,8}", 0..20),
        ) {
            let text = format!("f(\"{contents}\")\n{}", identifiers.join(" (x) \n"));
            prop_assert!(lex(&text, &[]).is_ok());
            check_lex(&text)?;
        }
    }

    #[test]
    fn offsets_and_brackets() {
        let tokens = lex("f(\"é\", x)\n", &[]).unwrap();
        assert_eq!(tokens.toks[2].end_cp, 5);
        assert_eq!(tokens.toks[2].end, Pos { line: 1, col: 7 });
        assert_eq!(tokens.toks[1].partner, 5);
        assert_eq!(tokens.toks.last().unwrap().nl_before, 1);
    }

    #[test]
    fn number_and_nested_comment() {
        let tokens = lex("0x1.p3 /* a /* b */ c */", &[]).unwrap();
        assert_eq!(tokens.text(0), "0x1.p3");
        assert_eq!(tokens.text(1), "/* a /* b */ c */");
    }
}
