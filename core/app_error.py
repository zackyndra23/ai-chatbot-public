from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

def register_error_handlers(app: FastAPI):
    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logging.exception("Unhandled exception")
        return JSONResponse({"error": "internal_error", "message": "Unexpected error"}, status_code=500)