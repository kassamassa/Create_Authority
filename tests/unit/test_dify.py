from app.services import dify


def test_translate_to_japanese_empty_string_returns_empty():
    assert dify.translate_to_japanese("") == ""


def test_call_workflow_success(mocker):
    mock_response = mocker.Mock()
    mock_response.json.return_value = {"data": {"outputs": {"translated_text": "こんにちは"}}}
    mock_response.raise_for_status.return_value = None
    mocker.patch("httpx.post", return_value=mock_response)

    result = dify.translate_to_japanese("hello")
    assert result == "こんにちは"
