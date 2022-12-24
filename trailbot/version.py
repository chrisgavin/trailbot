import importlib.metadata

import versio.version
import versio.version_scheme

def version() -> versio.version.Version:
	version_string = importlib.metadata.version("trailbot")
	return versio.version.Version(version_string, versio.version_scheme.Pep440VersionScheme)
