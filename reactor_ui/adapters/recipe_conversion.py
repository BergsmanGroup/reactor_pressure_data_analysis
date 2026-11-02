"""Export an in-memory recipe using the existing converter."""

from __future__ import annotations

from pathlib import Path

from convert_to_json import build_output_filename, build_payload, save_payload
from reactor_ui.models.recipe_document import RecipeDocument


def create_payload(document: RecipeDocument) -> dict:
    if not document.can_export or document.frame is None:
        raise ValueError("Cannot export the recipe: " + "; ".join(document.validation_errors))
    wait = document.wait_seconds
    if wait is None:
        raise ValueError("Wait time must be a finite non-negative number of seconds.")
    details = dict(document.details)
    details["WaitTime"] = int(wait) if wait.is_integer() else wait
    return build_payload(
        document.frame,
        username=build_output_filename(document.frame),
        details=details,
        start_time=document.start_time,
    )


def export_payload(document: RecipeDocument, path: str | Path) -> Path:
    target = Path(path)
    source = document.source_path
    if target.suffix.lower() != ".json":
        raise ValueError("Choose a .json file for the exported payload.")
    if source is not None and (target.resolve() == source.resolve() or (target.exists() and target.samefile(source))):
        raise ValueError("The payload cannot overwrite the source recipe sheet.")
    payload = create_payload(document)
    saved = save_payload(payload, target)
    document.mark_exported(saved)
    return saved
