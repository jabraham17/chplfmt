#![no_main]

use chplfmt_core::lexer::scan::lex;
use chplfmt_core::lexer::token::{Pos, TokenKind, NO_MATCH};
use libfuzzer_sys::fuzz_target;

fn advance(text: &str, pos: &mut Pos, offset_cp: &mut usize) {
    for ch in text.chars() {
        *offset_cp += 1;
        if ch == '\n' {
            pos.line += 1;
            pos.col = 1;
        } else {
            pos.col += ch.len_utf8() as u32;
        }
    }
}

fuzz_target!(|bytes: &[u8]| {
    let text = String::from_utf8_lossy(bytes);
    let Ok(tokens) = lex(&text, &[]) else {
        return;
    };

    let mut reconstructed = String::with_capacity(text.len());
    let mut cursor = 0;
    let mut pos = Pos { line: 1, col: 1 };
    let mut offset_cp = 0;
    let mut stack = Vec::new();
    for (index, token) in tokens.toks.iter().enumerate() {
        let start = token.start_byte as usize;
        let end = token.end_byte as usize;
        assert!(cursor <= start && start <= end && end <= text.len());
        let gap = &text[cursor..start];
        assert!(gap.bytes().all(|byte| b" \t\r\n\x0c".contains(&byte)));
        assert_eq!(token.ws_before, !gap.is_empty());
        assert_eq!(
            token.nl_before,
            gap.bytes().filter(|byte| *byte == b'\n').count() as u32
        );
        advance(gap, &mut pos, &mut offset_cp);
        assert_eq!(token.start, pos);
        assert_eq!(token.start_cp as usize, offset_cp);

        let token_text = tokens.text(index);
        reconstructed.push_str(gap);
        reconstructed.push_str(token_text);
        advance(token_text, &mut pos, &mut offset_cp);
        assert_eq!(token.end, pos);
        assert_eq!(token.end_cp as usize, offset_cp);
        cursor = end;

        match (token.kind, token_text) {
            (TokenKind::Punct, "(" | "[" | "{") => stack.push(index),
            (TokenKind::Punct, ")" | "]" | "}") => {
                let open = stack.pop().expect("closing bracket without opener");
                let expected = match token_text {
                    ")" => "(",
                    "]" => "[",
                    _ => "{",
                };
                assert_eq!(tokens.text(open), expected);
                assert_eq!(tokens.toks[open].partner, index as u32);
                assert_eq!(token.partner, open as u32);
            }
            _ => assert_eq!(token.partner, NO_MATCH),
        }
    }
    assert!(stack.is_empty());
    assert_eq!(cursor, text.len());
    assert_eq!(reconstructed, text);
    let eof = tokens.toks.last().expect("missing EOF token");
    assert_eq!(eof.kind, TokenKind::Eof);
    assert_eq!(eof.start_byte, eof.end_byte);
});
