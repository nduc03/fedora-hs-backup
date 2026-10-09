from installer.context import InstallContext


def run(context: InstallContext) -> None:
    context.log(f">>> Hook mẫu pre_install: {context.service_name}")
    # Khi cần chạy lệnh: context.runner.run(["lệnh", "tham-số"], privileged=True)
