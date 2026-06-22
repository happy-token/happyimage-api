from __future__ import annotations

from unittest import mock

from services import model_gateway_service


class _GatewayResponse:
    status_code = 200
    text = '{"created":1,"data":[{"url":"https://example.test/image.png"}]}'

    def json(self):
        return {"created": 1, "data": [{"url": "https://example.test/image.png"}]}


class _GatewaySession:
    attempts = 0

    def post(self, *args, **kwargs):
        type(self).attempts += 1
        if type(self).attempts == 1:
            raise RuntimeError(
                "Failed to perform, curl: (56) Connection closed abruptly. "
                "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
            )
        return _GatewayResponse()

    def close(self):
        pass


def test_edit_image_retries_retryable_gateway_disconnect():
    _GatewaySession.attempts = 0

    with mock.patch("requests.Session", side_effect=_GatewaySession):
        result = model_gateway_service.edit_image(
            {
                "model_gateway_base_url": "https://gateway.example.test/v1",
                "model_gateway_api_key": "sk-test",
                "model": "gpt-image-2",
                "prompt": "edit",
                "images": [(b"fake", "image.png", "image/png")],
            }
        )

    assert _GatewaySession.attempts == 2
    assert result["data"][0]["url"] == "https://example.test/image.png"


def test_edit_image_retries_tls_connect_error():
    class _TLSGatewaySession(_GatewaySession):
        attempts = 0

        def post(self, *args, **kwargs):
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise RuntimeError(
                    "Failed to perform, curl: (35) TLS connect error: "
                    "error:00000000:invalid library (0):OPENSSL_internal:invalid library (0)."
                )
            return _GatewayResponse()

    with mock.patch("requests.Session", side_effect=_TLSGatewaySession):
        result = model_gateway_service.edit_image(
            {
                "model_gateway_base_url": "https://gateway.example.test/v1",
                "model_gateway_api_key": "sk-test",
                "model": "gpt-image-2",
                "prompt": "edit",
                "images": [(b"fake", "image.png", "image/png")],
            }
        )

    assert _TLSGatewaySession.attempts == 2
    assert result["data"][0]["url"] == "https://example.test/image.png"


def test_gateway_requires_payload_provider():
    assert model_gateway_service.is_enabled("", "") is False
    try:
        model_gateway_service.generate_image({"prompt": "cat", "model": "gpt-image-2"})
    except model_gateway_service.ModelGatewayConfigurationError as exc:
        assert str(exc) == "请先在用户设置中配置模型供应商 Base URL 和 API Key。"
    else:
        raise AssertionError("generate_image should require user provider settings")


def test_humanize_gateway_error_prompts_recharge_for_quota():
    message = model_gateway_service.humanize_gateway_error("insufficient_quota: no enough credits")

    assert message == "模型供应商额度不足，请先充值或更换供应商后再试。"


def test_humanize_gateway_error_hides_curl_tls_details():
    message = model_gateway_service.humanize_gateway_error(
        "Failed to perform, curl: (35) TLS connect error: OPENSSL_internal:invalid library"
    )

    assert message == "连接模型供应商失败，请稍后重试；如果持续出现，请检查 Base URL 或网络代理。"
