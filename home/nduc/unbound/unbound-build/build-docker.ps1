function Wait-DockerReady {
    for ($i = 0; $i -lt 60; $i++) {
        & docker info > $null 2>&1
        if ($LastExitCode -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    Write-Error "Lỗi: Docker Engine không sẵn sàng sau 1 phút."
    exit 1
}

Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden

Wait-DockerReady

docker build -t forgejo.hs.lan/nduc/unbound:latest .
docker push --tls-verify=false forgejo.hs.lan/nduc/unbound:latest