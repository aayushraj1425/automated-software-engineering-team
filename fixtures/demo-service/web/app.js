async function loadItems() {
  const response = await fetch("/items");
  const data = await response.json();
  const list = document.getElementById("items");
  for (const item of data.items) {
    const entry = document.createElement("li");
    entry.textContent = item;
    list.appendChild(entry);
  }
}

loadItems();
