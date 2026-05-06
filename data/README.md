# data/ · 公开数据集

> 主办方提供的赛题四公开数据集放在此目录。**统一使用主办方版本，不得自行替换**。

## 目录结构

```
data/
├── README.md            ← 本文件
├── employee_*.csv       ← 员工分析（HR）
├── sales_*.csv          ← 销售订单
├── fin_*.csv            ← 财务损益
├── operator_*.csv       ← 运营商 ARPU
├── service_*.csv        ← 客服工单
├── retail_*.csv         ← 零售
├── traffic_*.csv        ← 交通
├── weather_*.csv        ← 气象
├── population_*.csv     ← 人口
├── movies_*.csv         ← 电影
├── sailing_*.csv        ← 试航
└── ... (15 个公开数据集)
```

## 数据准备步骤

1. **下载主办方公开数据集**（赛题四共 15 个）→ 解压到本目录
2. **生成 schema 缓存**：

```bash
cd backend-skeleton
source .venv/bin/activate
python tools/extract_schema.py --data-dir ../data --out ../schemas.json
```

3. **重启后端**让 Agent 加载 schema：

```bash
make stop && make run    # 或重启 uvicorn
```

## 注意事项

- ❌ **不要上传业务自造数据**到 GitAI（违反主办方规则）
- ❌ **不要修改主办方原始 CSV**（保证评分公平）
- ✅ 大文件（>50MB）已通过 `.gitignore` 排除入库；评委拉仓库后需自行准备数据
- ✅ 隐藏评测集格式与公开评测集一致，仅内容不同

## 隐私与安全

- 所有数据为主办方公开数据集，已脱敏
- 私有 / 客户数据**绝不上传**到本仓库或 GitAI
