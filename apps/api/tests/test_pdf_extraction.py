import asyncio

import httpx

from app.services.pdf_extraction import _download_pdf_response, _solve_acw_sc_v2_cookie


def test_solve_acw_sc_v2_cookie_from_sse_challenge_arg1():
    html = "<html><script>var arg1='8E99CFF4779F42591226A90F5BEE370802A050B8';</script></html>"

    assert _solve_acw_sc_v2_cookie(html) == "6a3f1ee077a5ee9652ecb3371a888ef93b1e2685"


def test_download_pdf_response_retries_after_acw_sc_v2_challenge():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<html><script>var arg1='8E99CFF4779F42591226A90F5BEE370802A050B8';document.cookie='acw_sc__v2=';</script></html>",
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.7\nfake",
            request=request,
        )

    async def run_case() -> httpx.Response:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            return await _download_pdf_response(
                client,
                "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-03-27/600362_test.pdf",
            )

    response = asyncio.run(run_case())

    assert len(calls) == 2
    assert response.content.startswith(b"%PDF")
    assert "acw_sc__v2=" in calls[1].headers.get("cookie", "")
