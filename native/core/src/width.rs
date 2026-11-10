mod width_table;

use width_table::WIDE_RANGES;
pub use width_table::{PYTHON_VERSION, UNICODE_VERSION};

pub fn char_width(ch: char) -> i64 {
    let code = u32::from(ch);
    if code < 0x1100 {
        return 1;
    }
    let index = WIDE_RANGES.partition_point(|&(_, hi)| hi < code);
    if index < WIDE_RANGES.len() && WIDE_RANGES[index].0 <= code {
        2
    } else {
        1
    }
}

pub fn display_width(text: &str, start_col: i64, tab_size: i64) -> Result<i64, &'static str> {
    if text.is_ascii() && !text.contains(['\t', '\n']) {
        return Ok(start_col + text.len() as i64);
    }
    let mut col = start_col;
    for ch in text.chars() {
        match ch {
            '\t' => {
                if tab_size == 0 {
                    return Err("integer modulo by zero");
                }
                let remainder = col.rem_euclid(tab_size.unsigned_abs() as i64);
                let python_modulo = if tab_size < 0 && remainder != 0 {
                    remainder + tab_size
                } else {
                    remainder
                };
                col += tab_size - python_modulo;
            }
            '\n' => col = 0,
            _ => col += char_width(ch),
        }
    }
    Ok(col)
}

#[cfg(test)]
mod tests {
    use super::{char_width, display_width};

    #[test]
    fn widths() {
        assert_eq!(char_width('a'), 1);
        assert_eq!(char_width('\u{301}'), 1);
        assert_eq!(char_width('中'), 2);
        assert_eq!(char_width('😀'), 2);
        assert_eq!(display_width("中\t", 0, 4), Ok(4));
        assert_eq!(display_width("ab\ncd", 3, 2), Ok(2));
        assert_eq!(display_width("\t", 3, 4), Ok(4));
        assert_eq!(display_width("\t", 3, 0), Err("integer modulo by zero"));
    }

    #[test]
    fn ranges_are_sorted_and_nonoverlapping() {
        let ranges = super::WIDE_RANGES;
        assert!(ranges.iter().all(|&(lo, hi)| lo >= 0x1100 && lo <= hi));
        assert!(ranges.windows(2).all(|pair| pair[0].1 < pair[1].0));
    }
}
