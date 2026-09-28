import logging

from PySide6.QtCore import QThread, Signal

from core.ai import AIError
from core.video_pipeline import RenderCancelled

logger = logging.getLogger("kv.ui.worker")


class TaskThread(QThread):
    """Runs one blocking job off the GUI thread. `job` receives a progress(stage, percent) callback."""

    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job

    def run(self):
        try:
            result = self._job(self.progress.emit)
        except AIError as error:
            logger.warning("task_failed type=%s", type(error).__name__)
            self.failed.emit(error.message)
        except RenderCancelled as error:
            logger.info("task_cancelled")
            self.failed.emit(str(error))
        except Exception as error:
            logger.exception("task_failed")
            self.failed.emit(str(error) or type(error).__name__)
        else:
            self.succeeded.emit(result)
