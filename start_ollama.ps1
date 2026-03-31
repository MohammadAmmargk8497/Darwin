# Start Ollama with GPU disabled
$env:OLLAMA_GPU_DISABLED = "1"
Write-Host "GPU Disabled: $env:OLLAMA_GPU_DISABLED"
Write-Host "Starting Ollama in CPU-only mode..."
ollama serve
