#[derive(Copy, Clone, PartialEq, Eq, Hash, Debug)]
#[repr(u8)]
pub enum TokenKind {
    Ident,
    Number,
    String,
    LineComment,
    BlockComment,
    Punct,
    Opaque,
    Eof,
}

#[derive(Copy, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Debug)]
pub struct Pos {
    pub line: u32,
    pub col: u32,
}

#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub struct Token {
    pub kind: TokenKind,
    pub ws_before: bool,
    pub nl_before: u32,
    pub start_byte: u32,
    pub end_byte: u32,
    pub start_cp: u32,
    pub end_cp: u32,
    pub start: Pos,
    pub end: Pos,
    pub partner: u32,
}

pub const NO_MATCH: u32 = u32::MAX;

pub struct Tokens<'s> {
    pub text: &'s str,
    pub toks: Vec<Token>,
}

impl Tokens<'_> {
    pub fn text(&self, index: usize) -> &str {
        let token = &self.toks[index];
        &self.text[token.start_byte as usize..token.end_byte as usize]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_text_uses_byte_offsets() {
        let tokens = Tokens {
            text: "\"é\"",
            toks: vec![Token {
                kind: TokenKind::String,
                ws_before: false,
                nl_before: 0,
                start_byte: 0,
                end_byte: 4,
                start_cp: 0,
                end_cp: 3,
                start: Pos { line: 1, col: 1 },
                end: Pos { line: 1, col: 5 },
                partner: NO_MATCH,
            }],
        };
        assert_eq!(tokens.text(0), "\"é\"");
    }
}
