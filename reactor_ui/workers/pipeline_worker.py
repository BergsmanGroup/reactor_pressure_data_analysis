"""Qt worker boundaries for processing and other potentially slow reads."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot

from pipeline import ReactorPipeline


class OperationWorker(QObject):
    progress = Signal(int, str)
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str)
    done = Signal()

    def __init__(
        self,
        label: str,
        operation: Callable[[Callable[[float], None], Callable[[str], None]], object],
    ) -> None:
        super().__init__()
        self.label = label
        self._operation = operation

    def _progress(self, percent: float) -> None:
        self.progress.emit(max(0, min(100, round(percent))), self.label)

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation(self._progress, self.log.emit)
        except Exception as exc:
            self.failed.emit(f"{self.label}: {type(exc).__name__}: {exc}")
        else:
            self.finished.emit(result)
        finally:
            self.done.emit()


class PipelineWorker(OperationWorker):
    def __init__(
        self,
        pipeline: ReactorPipeline,
        action: str,
        *,
        attach_temperature: bool = False,
        attach_ise: bool = False,
    ) -> None:
        actions = {"condense", "label_phases", "attach_temperature", "attach_ise", "generate_outputs", "run_all"}
        if action not in actions:
            raise ValueError(f"Unknown pipeline action: {action}")
        self.pipeline = pipeline
        self.action = action

        def execute(progress: Callable[[float], None], log: Callable[[str], None]) -> object:
            if action == "run_all":
                return pipeline.run_all(
                    progress_cb=progress,
                    log_cb=log,
                    attach_temperature=attach_temperature,
                    attach_ise=attach_ise,
                )
            if action == "attach_ise":
                pipeline.options.add_ise = True
            return getattr(pipeline, action)(progress_cb=progress, log_cb=log)

        super().__init__(action.replace("_", " ").title(), execute)
