.PHONY: help install dev mock real run stop logs clean eval schema

help:
	@echo "Table-Talker Make 命令："
	@echo "  make install     初始安装：拷 .env、拉镜像"
	@echo "  make dev         本地开发：分别起前端 + 后端（需开两个终端）"
	@echo "  make mock        Mock 模式启动（无需 API Key，演示用）"
	@echo "  make real        真实模式启动（需 API Key）"
	@echo "  make run         一键启动所有服务（docker-compose up -d）"
	@echo "  make stop        停止所有服务"
	@echo "  make logs        查看后端日志"
	@echo "  make eval        跑公开评测集 → 自测报告/"
	@echo "  make schema      抽取 data/ 下所有 CSV 的 schema"
	@echo "  make clean       清理生成文件"

install:
	@if [ ! -f .env ]; then \
		cp backend-skeleton/.env.example .env; \
		echo "✅ 已生成 .env，请编辑填入 QWEN_API_KEY"; \
	else \
		echo "ℹ️  .env 已存在"; \
	fi
	docker-compose pull
	docker-compose build

dev:
	@echo "请开两个终端："
	@echo "  终端 1: cd backend-skeleton && uvicorn main:app --reload --host 0.0.0.0 --port 8000"
	@echo "  终端 2: cd design-source && python3 -m http.server 8080"
	@echo "然后访问 http://localhost:8080/Table-Talker.html"

mock:
	MOCK_MODE=true docker-compose up -d
	@echo "✅ Mock 模式已启动"
	@echo "   前端: http://localhost:8080"
	@echo "   后端: http://localhost:8000/docs"

real:
	@if grep -q "sk-xxxxx" .env 2>/dev/null; then \
		echo "❌ .env 里还是占位 API Key，请先编辑"; \
		exit 1; \
	fi
	MOCK_MODE=false docker-compose up -d
	@echo "✅ 真实模式已启动"
	@echo "   前端: http://localhost:8080"
	@echo "   后端: http://localhost:8000/docs"

run: real

stop:
	docker-compose down

logs:
	docker-compose logs -f backend

eval:
	docker-compose exec backend python -c "import asyncio; from agent.orchestrator import run_agent_simple; asyncio.run(run_agent_simple('test'))"

schema:
	docker-compose exec backend python tools/extract_schema.py --data-dir /app/data --out /app/schemas.json

clean:
	docker-compose down -v
	rm -rf eval_results/* reports/*
