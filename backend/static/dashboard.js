document.getElementById("copy-url").addEventListener("click", async () => {
  const input = document.getElementById("mcp-url");
  try {
    await navigator.clipboard.writeText(input.value);
    document.getElementById("copy-status").textContent = "URL copied.";
  } catch {
    input.select();
    document.getElementById("copy-status").textContent = "Press Ctrl+C to copy the selected URL.";
  }
});
