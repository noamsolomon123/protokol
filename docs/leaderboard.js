// Render the leaderboard from the static JSON the export script produced.
fetch("data/leaderboard.json")
  .then((r) => (r.ok ? r.json() : { rows: [] }))
  .then((data) => {
    const rows = (data && data.rows) || [];
    const board = document.getElementById("board");
    if (!rows.length) {
      document.getElementById("empty").hidden = false;
      return;
    }
    for (const row of rows) {
      const li = document.createElement("li");
      li.className = "board-row";
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = row.full_name + (row.party ? ` (${row.party})` : "");
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = row.contradicted_count;
      li.append(name, count);
      board.appendChild(li);
    }
  })
  .catch(() => {
    document.getElementById("empty").hidden = false;
  });
