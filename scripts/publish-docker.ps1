# Publica imagens Eva no Docker Hub (opcional — ver DEPLOY_PORTAINER.md)
param(
    [Parameter(Mandatory = $true)]
    [string]$DockerHubUser,
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "Build API..."
docker build -t "${DockerHubUser}/iavendas-api:${Tag}" (Join-Path $root "backend")

Write-Host "Build Frontend..."
docker build -t "${DockerHubUser}/iavendas-frontend:${Tag}" (Join-Path $root "frontend")

Write-Host "Push..."
docker push "${DockerHubUser}/iavendas-api:${Tag}"
docker push "${DockerHubUser}/iavendas-frontend:${Tag}"

Write-Host "OK. No Portainer use docker-compose.hub.yml com DOCKERHUB_USER=$DockerHubUser"
