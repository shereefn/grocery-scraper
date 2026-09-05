document.addEventListener("DOMContentLoaded", () => {
    const isFoodPage = window.location.pathname.includes("/food");

    const headerHTML = `
      <div class="navbar">
        <div class="nav-left">
          <button class="hamburger" onclick="toggleSidebar()">&#9776;</button>
          
          <div class="brand-group">
            <select id="nav-city-select" class="nav-city-dropdown" aria-label="Select City">
              <option value="riyadh">Riyadh</option>
              <option value="jeddah">Jeddah</option>
              <option value="dammam">Dammam</option>
              <option value="mecca">Mecca</option>
              <option value="medina">Medina</option>
            </select>
            <h1>Go Deals</h1>
          </div>
        </div>
        
        <div class="nav-center">
          <div class="search-container">
              <input type="text" id="filter-product" placeholder="${isFoodPage ? 'Search for amazing food deals...' : 'Search for amazing grocery deals...'}" oninput="applyFilters()">
          </div>
        </div>
      
        <div class="nav-right">
          <a href="/" class="tab-btn ${!isFoodPage ? 'active' : 'inactive'}">🛒 Groceries</a>
          <a href="/food" class="tab-btn ${isFoodPage ? 'active' : 'inactive'}">🍽️ Food</a>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML("afterbegin", headerHTML);

    const cityDropdown = document.getElementById('nav-city-select');
    if(cityDropdown) {
        // Read current subdomain (e.g. "riyadh")[cite: 2]
        const currentHostname = window.location.hostname;
        const currentCity = currentHostname.split('.')[0];
        
        // Auto-select correct dropdown item[cite: 2]
        Array.from(cityDropdown.options).forEach(option => {
          if (option.value === currentCity) {
            option.selected = true;
          }
        });

        // Handle redirection on city change[cite: 2]
        cityDropdown.addEventListener('change', (e) => {
          const selectedCity = e.target.value;
          if (selectedCity && selectedCity !== currentCity) {
            window.location.href = `https://${selectedCity}.godeals.me`;
          }
        });
    }
});