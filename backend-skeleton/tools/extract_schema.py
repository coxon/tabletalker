"""离线 schema 抽取脚本。

跑一次：
    python tools/extract_schema.py --data-dir ./data --out ./schemas.json

会读取 data/ 下所有 CSV/Parquet/Excel，生成统一 schema 文件。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def extract_one(path: Path, n_samples: int = 5) -> dict:
    """抽取单个数据集 schema。"""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path, nrows=10000, encoding_errors="ignore")
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, nrows=10000)
    elif suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        return {}

    schema = {
        "name": path.stem,
        "source_path": str(path),
        "n_rows_sampled": len(df),
        "description": "",  # 用户可手动补
        "columns": [],
    }
    for col in df.columns:
        col_info = {
            "name": col,
            "dtype": str(df[col].dtype),
            "null_rate": float(df[col].isna().mean()),
            "business_term": "",  # 用户可手动补
        }
        if pd.api.types.is_numeric_dtype(df[col]):
            col_info.update({
                "min": float(df[col].min()) if not pd.isna(df[col].min()) else None,
                "max": float(df[col].max()) if not pd.isna(df[col].max()) else None,
                "mean": float(df[col].mean()) if not pd.isna(df[col].mean()) else None,
            })
        else:
            uniq = df[col].dropna().astype(str).unique()[:20]
            col_info["sample_values"] = uniq.tolist()
        schema["columns"].append(col_info)

    schema["head"] = df.head(n_samples).fillna("").astype(str).to_dict(orient="records")
    return schema


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="./data")
    parser.add_argument("--out", default="./schemas.json")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"⚠️  data 目录不存在：{data_dir}")
        return

    schemas = {}
    for ext in ("*.csv", "*.xlsx", "*.parquet"):
        for f in data_dir.glob(ext):
            print(f"  扫描 {f.name}...")
            try:
                schemas[f.stem] = extract_one(f)
            except Exception as e:
                print(f"  ✗ 跳过 {f.name}: {e}")

    Path(args.out).write_text(json.dumps(schemas, ensure_ascii=False, indent=2))
    print(f"\n✅ {len(schemas)} 个数据集 schema 写入 {args.out}")


if __name__ == "__main__":
    main()
