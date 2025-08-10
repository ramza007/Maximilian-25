// Minimal client-side helpers
document.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-remove]");
  if(btn){
    const id = btn.getAttribute("data-remove");
    if(confirm("Remove this diary entry?")){
      fetch(`/api/diary/${id}`, {method: "DELETE"})
        .then(r => r.json())
        .then(ok => { if(ok.ok){ location.reload(); } });
    }
  }
});

const addForm = document.querySelector("#add-to-diary");
if(addForm){
  addForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(addForm));
    document.getElementById("add-result").textContent = "Saving…";
    fetch("/api/diary", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(data)
    })
    .then(r => r.json())
    .then(res => {
      if(res.ok){
        document.getElementById("add-result").textContent = "Added ✓";
        setTimeout(() => window.location.href = "/diary", 400);
      }else{
        document.getElementById("add-result").textContent = "Error: " + (res.error || "unknown");
      }
    })
    .catch(err => {
      document.getElementById("add-result").textContent = "Error: " + err.message;
    });
  });
}
