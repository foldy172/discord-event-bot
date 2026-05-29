import logging
import threading

from config import WEB_DEV_PASSWORD, WEB_DEV_USERNAME, WEB_ENABLED, WEB_HOST, WEB_PORT

logger = logging.getLogger(__name__)


def start_web_panel_in_background() -> bool:
    if not WEB_ENABLED:
        logger.info("Веб-панель отключена (WEB_ENABLED=false).")
        return False
    if not WEB_DEV_PASSWORD.strip():
        logger.warning(
            "Веб-панель не запущена: укажите WEB_DEV_PASSWORD (или WEB_PASSWORD) в .env "
            "(или WEB_ENABLED=false)."
        )
        return False

    def _run() -> None:
        import uvicorn

        from web.app import app

        uvicorn.run(
            app,
            host=WEB_HOST,
            port=WEB_PORT,
            log_level="info",
        )

    thread = threading.Thread(target=_run, name="event-web-panel", daemon=True)
    thread.start()
    logger.info(
        "Веб-панель: http://%s:%s (разработчик: %s)",
        WEB_HOST,
        WEB_PORT,
        WEB_DEV_USERNAME,
    )
    return True
