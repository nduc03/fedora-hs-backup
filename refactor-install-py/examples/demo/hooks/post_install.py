from installer.context import InstallContext


def run(context: InstallContext) -> None:
    context.log(f">>> Hook mẫu post_install: {context.service_name}")
