az login --identity
az acr login --name deletesfservice
Write-Output 'Inspecting Docker image...'
$containerID=docker ps -a -q --filter ancestor=deletesfservice.azurecr.io/netflixwatcher
if (![string]::IsNullOrEmpty($containerID)) {
Write-Output 'Removing container with ID: $containerID'
docker kill $containerID
docker rm $containerID
} else {
Write-Output 'Image does not exist. Pulling...'
docker pull deletesfservice.azurecr.io/netflixwatcher:latest
Write-Output 'Image pulled.'
}
Write-Output 'Running Docker container...'
docker run -d --restart always deletesfservice.azurecr.io/netflixwatcher:latest
Write-Output 'Container started.'
Write-Output 'Listing running Docker containers...'
docker ps
Write-Output 'Done.'