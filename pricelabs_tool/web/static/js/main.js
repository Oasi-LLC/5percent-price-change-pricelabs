document.addEventListener('DOMContentLoaded', function() {
    const selectAll = document.getElementById('selectAll');
    const pmsFilter = document.getElementById('pmsFilter');
    const applyButton = document.getElementById('applyChanges');
    const statusDiv = document.getElementById('status');
    const dryRun = document.getElementById('dryRun');
    const dryRunSummary = document.getElementById('dryRunSummary');
    const listingsTable = document.getElementById('listingsTable');
    const refreshButton = document.getElementById('refreshListings');
    const refreshStatus = document.getElementById('refreshStatus');
    let listingsData = [];
    
    // Enable/disable apply button based on selection
    function updateApplyButton() {
        const hasAdjustment = document.querySelector('input[name="adjustment"]:checked');
        applyButton.disabled = !hasAdjustment;
    }
    
    // Fetch and render listings
    async function loadListings() {
        listingsTable.innerHTML = '<div>Loading listings...</div>';
        try {
            const response = await fetch(`/api/listings`);
            const data = await response.json();
            if (data.status === 'success') {
                listingsData = data.listings;
                renderListingsTable(listingsData);
            } else {
                listingsTable.innerHTML = '<div class="text-danger">Failed to load listings.</div>';
            }
        } catch (e) {
            listingsTable.innerHTML = '<div class="text-danger">Error loading listings.</div>';
        }
    }

    function renderListingsTable(listings) {
        if (!listings.length) {
            listingsTable.innerHTML = '<div>No listings found.</div>';
            return;
        }
        let html = '<table class="table table-sm table-bordered"><thead><tr>' +
            '<th><input type="checkbox" id="selectAllListings"></th>' +
            '<th>Name</th><th>ID</th></tr></thead><tbody>';
        listings.forEach((listing, idx) => {
            html += `<tr><td><input type="checkbox" class="listing-checkbox" data-id="${listing.id}" checked></td>` +
                `<td>${listing.name}</td><td>${listing.id}</td></tr>`;
        });
        html += '</tbody></table>';
        listingsTable.innerHTML = html;

        // Wire up select all
        const selectAllListings = document.getElementById('selectAllListings');
        const checkboxes = document.querySelectorAll('.listing-checkbox');
        selectAllListings.checked = true;
        selectAllListings.addEventListener('change', function() {
            checkboxes.forEach(cb => { cb.checked = selectAllListings.checked; });
        });
        checkboxes.forEach(cb => {
            cb.addEventListener('change', function() {
                if (!cb.checked) selectAllListings.checked = false;
                else if ([...checkboxes].every(c => c.checked)) selectAllListings.checked = true;
            });
        });
    }

    // Refresh listings functionality
    refreshButton.addEventListener('click', async function() {
        refreshButton.disabled = true;
        refreshStatus.innerHTML = '<span class="text-info">Refreshing listings...</span>';
        
        try {
            const response = await fetch('/api/refresh-listings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            const data = await response.json();
            
            if (data.status === 'success') {
                listingsData = data.listings;
                renderListingsTable(listingsData);
                refreshStatus.innerHTML = `<span class="text-success">✓ Refreshed ${data.count} listings</span>`;
            } else {
                refreshStatus.innerHTML = `<span class="text-danger">✗ Error: ${data.message}</span>`;
            }
        } catch (e) {
            refreshStatus.innerHTML = '<span class="text-danger">✗ Network error</span>';
        } finally {
            refreshButton.disabled = false;
            // Clear status after 3 seconds
            setTimeout(() => {
                refreshStatus.innerHTML = '';
            }, 3000);
        }
    });

    // Load listings on page load and when PMS filter changes
    loadListings();
    
    // Handle form submission
    applyButton.addEventListener('click', async function() {
        const increase = document.getElementById('increase').checked;
        const isDryRun = dryRun.checked;
        // Get selected listing IDs
        const selectedIds = Array.from(document.querySelectorAll('.listing-checkbox:checked')).map(cb => cb.getAttribute('data-id'));
        if (selectedIds.length === 0) {
            statusDiv.innerHTML = '<div class="alert alert-warning">Please select at least one listing.</div>';
            return;
        }
        
        statusDiv.innerHTML = '<div class="alert alert-info">Processing listings in batches of 20 to avoid rate limits...</div>';
        dryRunSummary.style.display = 'none';
        
        try {
            const response = await fetch('/api/update-prices', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    increase: increase,
                    dry_run: isDryRun,
                    listing_ids: selectedIds
                })
            });
            
            const data = await response.json();
            
            if (data.status === 'success') {
                if (isDryRun && data.summary) {
                    // Show dry run summary
                    dryRunSummary.style.display = 'block';
                    let summaryHtml = '';
                    data.summary.forEach(item => {
                        summaryHtml += `
                            <div class="card mb-3">
                                <div class="card-body">
                                    <h5 class="card-title">${item.name}</h5>
                                    <p class="card-text text-muted">ID: ${item.id}</p>
                                    <p class="card-text">${item.changes} price(s) would be updated</p>`;
                        if (item.price_changes && item.price_changes.length > 0) {
                            summaryHtml += `
                                <div class="mt-2">
                                    <h6 class="card-subtitle mb-2">First 5 dates affected:</h6>
                                    <ul class="list-unstyled">`;
                            item.price_changes.forEach(change => {
                                summaryHtml += `
                                    <li class="mb-1">
                                        <span class="fw-bold">${change.date}:</span>
                                        <span class="text-muted">${change.old_price} ${change.currency}</span>
                                        <span class="text-muted">→</span>
                                        <span class="text-success">${change.new_price} ${change.currency}</span>
                                    </li>`;
                            });
                            summaryHtml += `</ul></div>`;
                        }
                        summaryHtml += `</div></div>`;
                    });
                    dryRunSummary.querySelector('.dry-run-listings').innerHTML = summaryHtml;
                    statusDiv.innerHTML = '<div class="alert alert-info">Dry run completed. Review the changes below.</div>';
                } else {
                    const successCount = data.results.filter(r => r.status === 'success').length;
                    const errorCount = data.results.filter(r => r.status === 'error').length;
                    
                    statusDiv.innerHTML = `
                        <div class="alert alert-success">
                            Successfully updated ${successCount} listings.
                            ${errorCount > 0 ? `<br>Failed to update ${errorCount} listings.` : ''}
                        </div>
                    `;
                }
            } else {
                statusDiv.innerHTML = `
                    <div class="alert alert-danger">
                        Error: ${data.message}
                    </div>
                `;
            }
        } catch (error) {
            statusDiv.innerHTML = `
                <div class="alert alert-danger">
                    Error: ${error.message}
                </div>
            `;
        }
    });
    
    // Update button state when radio buttons change
    document.querySelectorAll('input[name="adjustment"]').forEach(radio => {
        radio.addEventListener('change', updateApplyButton);
    });
}); 