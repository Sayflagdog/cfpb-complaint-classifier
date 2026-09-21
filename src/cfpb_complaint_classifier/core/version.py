from importlib.metadata import version


def get_application_version() -> str:
    return version("cfpb-complaint-classifier")
