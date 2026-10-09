from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from playwright.sync_api import sync_playwright

from .models import BoardExport, BoardRevision


def render_pages(snapshot):
    html = render_to_string("board/print.html", {"snapshot": snapshot})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1440}, device_scale_factor=1)
            page.route("**/*", lambda route: route.abort())
            page.set_content(html, wait_until="load")
            page.wait_for_function("window.boardReady === true", timeout=30000)
            if page.evaluate("""() => [...document.querySelectorAll('.print-content')].some(
                element => element.scrollHeight > element.clientHeight + 1
                    || element.scrollWidth > element.clientWidth + 1
            )"""):
                raise ValueError("Board content exceeds its page bounds.")
            pages = page.locator(".print-page")
            return [pages.nth(index).screenshot(type="png") for index in range(pages.count())]
        finally:
            browser.close()


def ensure_exports(revision, user):
    existing = list(revision.exports.order_by("id"))
    if existing:
        return existing
    images = render_pages(revision.snapshot)
    created = []
    try:
        with transaction.atomic():
            locked = BoardRevision.objects.select_for_update().get(pk=revision.pk)
            existing = list(locked.exports.order_by("id"))
            if existing:
                return existing
            for index, image in enumerate(images, 1):
                export = BoardExport(board=locked.board, revision=locked, created_by=user)
                export.file.save(
                    f"board-{locked.board_id}-v{locked.number}-{index}.png",
                    ContentFile(image), save=False,
                )
                created.append(export)
                export.save()
        return created
    except Exception:
        for export in created:
            export.file.delete(save=False)
        raise
