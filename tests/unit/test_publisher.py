from app.services import publisher


def test_notify_slack_skips_when_webhook_not_configured(mocker):
    mocker.patch.object(publisher, "SLACK_WEBHOOK_URL", "")
    post_mock = mocker.patch("httpx.post")

    publisher.notify_slack("テストメッセージ")

    post_mock.assert_not_called()


def test_notify_slack_posts_when_webhook_configured(mocker):
    mocker.patch.object(publisher, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/dummy")
    post_mock = mocker.patch("httpx.post")

    publisher.notify_slack("テストメッセージ")

    post_mock.assert_called_once()
