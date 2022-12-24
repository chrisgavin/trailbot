import trailbot.version

def test_version_returns_consistent_version_number() -> None:
	assert trailbot.version.version() == trailbot.version.version()
