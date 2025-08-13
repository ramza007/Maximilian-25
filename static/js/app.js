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

// user dropdown
const userBtn = document.getElementById("userMenuBtn");
const userMenu = document.getElementById("userMenu");
if (userBtn && userMenu) {
  userBtn.addEventListener("click", () => {
    const isHidden = userMenu.hasAttribute("hidden");
    userMenu.toggleAttribute("hidden", !isHidden ? true : false);
    userBtn.setAttribute("aria-expanded", isHidden ? "true" : "false");
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".user-menu")) {
      userMenu.setAttribute("hidden", "");
      userBtn.setAttribute("aria-expanded", "false");
    }
  });
}

// star rating -> hidden input (stores x2)
// document.querySelectorAll(".stars").forEach((wrap)=>{
//   const input = document.getElementById("ratingInput");
//   wrap.querySelectorAll(".star").forEach(btn=>{
//     btn.addEventListener("click", ()=>{
//       const val = parseInt(btn.dataset.value, 10); // 1..5
//       input.value = String(val * 2);               // store 1..10
//       wrap.querySelectorAll(".star").forEach(b=>{
//         b.classList.toggle("active", parseInt(b.dataset.value,10) <= val);
//       });
//     });
//   });
// });

// star rating -> hidden input (stores 1..10)
document.querySelectorAll(".stars").forEach((wrap)=>{
  const input = document.getElementById("ratingInput");
  wrap.querySelectorAll(".star").forEach(btn=>{
    btn.addEventListener("click", ()=>{
      const stars = parseInt(btn.dataset.value, 10); // 1..5
      input.value = String(stars * 2);               // save 2,4,6,8,10
      wrap.querySelectorAll(".star").forEach(b=>{
        b.classList.toggle("active", parseInt(b.dataset.value,10) <= stars);
      });
    });
  });
});




// focus search with '/'
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey &&
      !e.target.matches("input, textarea")) {
    e.preventDefault();
    (document.querySelector(".nav-search input") ||
     document.querySelector(".bottom-search input"))?.focus();
  }
});

// keep values in sync across the two forms
const topSearch = document.querySelector(".nav-search input");
const bottomSearch = document.querySelector(".bottom-search input");
[topSearch, bottomSearch].forEach(el => {
  if (!el) return;
  el.addEventListener("input", () => {
    const other = el === topSearch ? bottomSearch : topSearch;
    if (other && other.value !== el.value) other.value = el.value;
  });
});

// Make cast panel the same height as the poster (and keep it on resize)
// (function syncCastHeight(){
//   const poster = document.querySelector(".detail-poster");
//   const rail   = document.querySelector(".cast-rail");
//   if (!poster || !rail) return;

//   function apply(){
//     const h = poster.getBoundingClientRect().height;
//     rail.style.setProperty("--poster-equal-h", `${Math.max(220, Math.round(h))}px`);
//   }
//   window.addEventListener("load", apply, {once:true});
//   window.addEventListener("resize", ()=> requestAnimationFrame(apply));
//   // also recalc after poster image loads
//   poster.addEventListener("load", apply);
// })();

// Keep cast rail the same height as the poster, always.
(function syncCastRailHeight(){
  const poster = document.querySelector(".detail-poster");
  const rail   = document.querySelector(".cast-rail");
  if (!poster || !rail) return;

  function applyHeight(){
    const h = poster.getBoundingClientRect().height || poster.offsetHeight || 0;
    if (h > 0) rail.style.setProperty("--poster-equal-h", `${Math.round(h)}px`);
  }

  // initial + on load
  applyHeight();
  if (!poster.complete) poster.addEventListener("load", applyHeight);

  // on resize
  window.addEventListener("resize", () => requestAnimationFrame(applyHeight));

  // watch for any layout/image changes
  if ("ResizeObserver" in window) {
    const ro = new ResizeObserver(() => applyHeight());
    ro.observe(poster);
  }
})();
