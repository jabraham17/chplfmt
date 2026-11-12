use std::fs;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

fn collect_sources(dir: &Path, files: &mut Vec<PathBuf>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path
            .file_name()
            .is_some_and(|name| name == "target" || name == "fuzz")
        {
            continue;
        }
        if path.is_dir() {
            collect_sources(&path, files)?;
        } else if matches!(
            path.extension().and_then(|ext| ext.to_str()),
            Some("rs" | "toml" | "lock")
        ) {
            files.push(path);
        }
    }
    Ok(())
}

fn main() -> std::io::Result<()> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let mut files = Vec::new();
    collect_sources(root, &mut files)?;
    files.sort_by(|left, right| left.to_str().unwrap().cmp(right.to_str().unwrap()));

    let mut hash = Sha256::new();
    for path in files {
        let relative = path.strip_prefix(root).unwrap();
        hash.update(relative.to_str().unwrap().as_bytes());
        hash.update([0]);
        hash.update(fs::read(&path)?);
        hash.update([0]);
        println!("cargo:rerun-if-changed={}", path.display());
    }
    println!("cargo:rerun-if-changed={}", root.join("core").display());
    println!("cargo:rerun-if-changed={}", root.join("py").display());
    println!("cargo:rustc-env=CHPLFMT_NATIVE_BUILD={:x}", hash.finalize());
    Ok(())
}
