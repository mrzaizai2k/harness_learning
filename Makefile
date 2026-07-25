be:
	uvicorn main:app --reload --port 8000

fe:
	cd frontend && npm run dev