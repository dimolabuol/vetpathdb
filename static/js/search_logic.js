// AI Search Logic and Results Display

let isSearchInProgress = false;
let activeTaskId = null;
let pollingInterval = null;
let searchDebounceTimer = null;
let lastClickTime = 0;

function handleSearchClick() {
    const searchButton = document.querySelector('.ai-controls button');
    const currentTime = Date.now();
    
    // Prevent rapid clicking (debounce with 500ms)
    if (currentTime - lastClickTime < 500) {
        console.log('Ignoring rapid click');
        return;
    }
    lastClickTime = currentTime;
    
    // Immediately hide the search placeholder
    document.getElementById('searchPlaceholder').style.display = 'none';
    
    console.log('Search button clicked, isSearchInProgress:', isSearchInProgress);
    
    // If search is running, stop it
    if (isSearchInProgress) {
        console.log('Attempting to stop search...');
        stopSearch(true); // Pass true to indicate this is a user-initiated cancel
        return;
    }
    
    // Clear any existing debounce timer
    if (searchDebounceTimer) {
        clearTimeout(searchDebounceTimer);
    }
    
    // Set a debounce timer to prevent multiple search requests
    searchDebounceTimer = setTimeout(() => {
        // Otherwise start new search
        searchButton.disabled = false; // Keep button enabled so it can be clicked to stop
        isSearchInProgress = true;
        searchButton.textContent = 'Stop Search';
        searchButton.classList.add('stop-search');
        performAiSearch();
        searchDebounceTimer = null;
    }, 300);
}

// Add event listener for Enter key in search textbox
document.addEventListener('DOMContentLoaded', function() {
    const searchTextbox = document.getElementById('aiSearchQuery');
    if (searchTextbox) {
        searchTextbox.addEventListener('keypress', function(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault(); // Prevent default behavior (newline)
                handleSearchClick(); // Trigger the same function as clicking the button
            }
        });
    }
});

function clearSearch() {
    // Clear results only
    document.getElementById('searchResults').innerHTML = '';
    document.getElementById('analysisResults').innerHTML = '';
    // Reset any search state
    if (activeTaskId && pollingInterval) {
        stopSearch();
    }
    
    // Show the search placeholder again
    document.getElementById('searchPlaceholder').style.display = 'flex';
}

function stopSearch(userInitiated = false) {
    console.log('stopSearch called, activeTaskId:', activeTaskId, 'pollingInterval:', !!pollingInterval);
    
    // First, clear any UI timers to prevent further updates
    if (pollingInterval) {
        console.log('Clearing polling interval');
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
    
    // Reset all UI state immediately
    const searchButton = document.querySelector('.ai-controls button');
    searchButton.classList.remove('loading', 'stop-search');
    searchButton.disabled = false;
    searchButton.textContent = 'Search';
    
    // Clear search debounce timer if it exists
    if (searchDebounceTimer) {
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = null;
    }
    
    // Reset search state variables
    isSearchInProgress = false;
    
    // Only make the cancel request if we have an active task ID
    if (activeTaskId) {
        const currentTaskId = activeTaskId; // Store for closure
        activeTaskId = null; // Clear immediately to prevent race conditions
        
        console.log('Sending cancel request to server for task:', currentTaskId);
        fetch(`/api/ai-search/${currentTaskId}/cancel`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            console.log('Cancel response:', data);
            
            // Only display results if this was user-initiated (not an auto-cleanup)
            if (userInitiated) {
                // Check if we have partial results
                if (data.partial_results && data.partial_results.length > 0) {
                    console.log(`Displaying ${data.partial_results.length} partial results`);
                    
                    // Display partial results
                    displayAiSearchResults(data.partial_results);
                    
                    // Show a notification that these are partial results
                    const resultsDiv = document.getElementById('searchResults');
                    const resultCountDiv = resultsDiv.querySelector('.result-count');
                    if (resultCountDiv) {
                        resultCountDiv.style.backgroundColor = 'var(--warning-light)';
                        resultCountDiv.style.border = '1px solid var(--warning-border)';
                        resultCountDiv.innerHTML = `
                            <i class="fas fa-exclamation-triangle"></i> 
                            Search cancelled - showing ${data.partial_results.length} partial results
                            <button onclick="exportToCSV()" class="export-button">Export to CSV</button>
                        `;
                    }
                } else {
                    // No partial results, show cancelled message
                    document.getElementById('searchResults').innerHTML = `
                        <div class="search-results-container">
                            <div class="result-count" style="background-color: var(--accent-light); border: 1px solid var(--accent-border);">
                                <i class="fas fa-ban"></i> Search cancelled by user
                            </div>
                        </div>`;
                }
            }
        })
        .catch(error => {
            console.error('Error canceling search:', error);
            // Show generic cancelled message on error if user-initiated
            if (userInitiated) {
                document.getElementById('searchResults').innerHTML = `
                    <div class="search-results-container">
                        <div class="result-count" style="background-color: var(--accent-light); border: 1px solid var(--accent-border);">
                            <i class="fas fa-ban"></i> Search cancelled by user
                        </div>
                    </div>`;
            }
        });
    } else {
        // If no active task, just show cancelled message if user-initiated
        if (userInitiated) {
            document.getElementById('searchResults').innerHTML = `
                <div class="search-results-container">
                    <div class="result-count" style="background-color: var(--accent-light); border: 1px solid var(--accent-border);">
                        <i class="fas fa-ban"></i> Search cancelled
                    </div>
                </div>`;
        }
    }
    
    console.log('Search stopped, states reset');
}

// Track the last stage for transition effects
let lastStage = '';

// Function to handle stage transitions with visual feedback
function handleStageTransition(currentStage) {
    if (lastStage && lastStage !== currentStage) {
        const indicator = document.querySelector('.loading-indicator');
        if (indicator) {
            indicator.classList.add('stage-transition');
            setTimeout(() => {
                indicator.classList.remove('stage-transition');
            }, 1000);
        }
    }
    lastStage = currentStage;
}

// Function to show queued status with position
function showQueuedStatus(statusData) {
    const statusContainer = document.querySelector('.loading-status');
    const progressDetails = document.querySelector('.progress-details');

    if (!statusContainer || !progressDetails) return;

    const position = statusData.queue_position || '?';
    const queuedCount = statusData.queued_count || position;

    // Update status container
    statusContainer.innerHTML = `
        <span class="status-icon"><i class="fas fa-hourglass-half"></i></span>
        <span>Search queued</span>
        <span class="stage-badge" style="background-color: var(--warning-color);">queued</span>
    `;

    // Update progress details
    progressDetails.innerHTML = `
        <div class="stage-description">
            <i class="fas fa-info-circle"></i>
            Your search is queued at position <strong>${position}</strong>
            ${queuedCount !== position ? ` of ${queuedCount}` : ''}
        </div>
        <div class="stage-description" style="margin-top: 10px;">
            <i class="fas fa-clock"></i>
            The search will start automatically when capacity is available.
            You can view all queued searches in the Queue panel.
        </div>
    `;

    // Set progress bar to minimal
    const progressFill = document.querySelector('.progress-fill');
    if (progressFill) {
        progressFill.style.width = '2%';
    }
}

// Function to update the progress display with enhanced visuals
function updateProgressDisplay(statusData, aiAnalysis) {
    const progressFill = document.querySelector('.progress-fill');
    const statusContainer = document.querySelector('.loading-status');
    const progressDetails = document.querySelector('.progress-details');
    
    // Add this check to prevent errors if elements don't exist
    if (!progressFill || !statusContainer || !progressDetails) {
        console.log("Progress display elements not found, skipping update");
        return; // Exit the function early if any element is missing
    }

    // Get task_id - prefer from statusData, fallback to activeTaskId
    const taskId = statusData.task_id || activeTaskId;

    // Determine the search mode
    const mode = !aiAnalysis ? 'semantic' : 'AI';
    
    // Set up stage information
    const stages = {
        'preparing': { 
            icon: 'fa-cog fa-spin', 
            text: 'Preparing search query',
            progress: 5,
            color: 'var(--primary-color)'
        },
        'vector_search': { 
            icon: 'fa-search', 
            text: 'Performing semantic search',
            progress: 20,
            color: 'var(--tool-similar)'
        },
        'preparing_analysis': { 
            icon: 'fa-brain', 
            text: 'Preparing AI analysis',
            progress: 30,
            color: 'var(--tool-morphology)'
        },
        'llm_analysis': { 
            icon: 'fa-robot', 
            text: 'Running AI analysis',
            progress: 40,
            color: 'var(--tool-ihc)'
        },
        'analyzing': { 
            icon: 'fa-microscope', 
            text: 'Analyzing results',
            progress: 50,
            color: 'var(--tool-breeds)'
        }
    };
    
    // Get current stage info
    const currentStage = statusData.stage || 'preparing';
    const stageInfo = stages[currentStage] || stages.preparing;
    
    // Handle stage transition animation
    handleStageTransition(currentStage);
    
    // Calculate progress percentage
    let progressPercent = stageInfo.progress;
    
    // For analyzing stage, use actual progress
    if (currentStage === 'analyzing' && statusData.total_cases && statusData.processed_cases !== undefined) {
        const caseProgress = Math.min(100, Math.round((statusData.processed_cases / statusData.total_cases) * 100));
        // Scale from 50% to 95% based on analysis progress
        progressPercent = 50 + (caseProgress * 0.45);
    }
    
    // Update progress bar
    progressFill.style.width = `${progressPercent}%`;
    progressFill.style.backgroundColor = stageInfo.color;
    
    // Update status text with icon
    statusContainer.innerHTML = `
        <span class="status-icon"><i class="fas ${stageInfo.icon}"></i></span>
        <span>${stageInfo.text}</span>
        <span class="stage-badge">${currentStage.replace('_', ' ')}</span>
    `;
    
    // Update details text
    let detailsHTML = '';
    
    if (currentStage === 'analyzing') {
        if (statusData.total_cases && statusData.processed_cases !== undefined) {
            const percent = Math.min(100, Math.round((statusData.processed_cases / statusData.total_cases) * 100));
            detailsHTML = `
                <div class="progress-stats">
                    <div class="stat-item">
                        <span class="stat-value">${statusData.processed_cases}</span>
                        <span class="stat-label">Processed</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-value">${statusData.total_cases}</span>
                        <span class="stat-label">Total</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-value">${percent}%</span>
                        <span class="stat-label">Complete</span>
                    </div>
                </div>
            `;
            
            // Add relevant cases count if available
            if (statusData.relevant_found !== undefined) {
                detailsHTML += `
                    <div class="relevant-cases">
                        <i class="fas fa-check-circle"></i> Found ${statusData.relevant_found} relevant cases so far
                        ${statusData.relevant_found > 0 && taskId ?
                            `<button class="view-partial-btn" onclick="viewPartialResults('${taskId}', ${statusData.relevant_found})" style="margin-left: 15px; padding: 5px 12px; background: var(--primary-color); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">
                                <i class="fas fa-eye"></i> View Results
                            </button>`
                            : ''
                        }
                    </div>
                `;
            }
        }
    } else {
        detailsHTML = `<div class="stage-description">${statusData.stage_description || 'Processing...'}</div>`;
    }
    
    progressDetails.innerHTML = detailsHTML;
}

async function performAiSearch(directQuery = null) {
    // Generate a unique client-side ID for this search attempt
    const searchAttemptId = Date.now().toString();
    window.currentSearchAttempt = searchAttemptId;
    
    // Immediately hide the search placeholder
    document.getElementById('searchPlaceholder').style.display = 'none';
    
    const query = directQuery || document.getElementById('aiSearchQuery').value;
    const aiAnalysis = document.getElementById('aiAnalysis').checked;
    window.semanticOnly = !aiAnalysis;
    const searchButton = document.querySelector('.ai-controls button');
    
    console.log(`Starting performAiSearch (${searchAttemptId}), semantic only:`, window.semanticOnly);

    // Treat a single whitespace-free token that contains a digit as a case-ID
    // lookup (e.g. "90001", "ACC-002317", "2014/057"); anything with spaces or
    // no digits is treated as a natural-language search instead.
    const trimmedQuery = query.trim();
    const caseIdPattern = /^[\w./-]{1,32}$/;
    if (caseIdPattern.test(trimmedQuery) && /\d/.test(trimmedQuery)) {
        try {
            // Convert to uppercase before querying
            const caseId = trimmedQuery.toUpperCase();
            const response = await fetch(`/api/case/${caseId}`);
            if (!response.ok) {
                throw new Error('Case not found');
            }
            const caseData = await response.json();
            displayAiSearchResults([caseData.case]); // Wrap single case in array
            searchButton.classList.remove('loading');
            searchButton.textContent = 'Search';
            searchButton.disabled = false;
            isSearchInProgress = false;
            return;
        } catch (error) {
            console.error('Error fetching case:', error);
            alert('Case not found or error occurred');
            searchButton.classList.remove('loading');
            searchButton.disabled = false;
            isSearchInProgress = false;
            return;
        }
    }
    
    if (!query.trim()) {
        alert('Please enter a search query');
        searchButton.classList.remove('loading', 'stop-search');
        searchButton.textContent = 'Search';
        searchButton.disabled = false;
        isSearchInProgress = false;
        return;
    }
    
    // Clear any existing polling
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
    
    // Reset last stage for new search
    lastStage = '';
    
    // Loading state already set in handleSearchClick()
    
    try {
        console.log(`Search attempt ${searchAttemptId}: Starting new search request`);
        const startTime = Date.now();
        
        // Initial request to start the search
        const response = await fetch('/api/ai-search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                depth: document.getElementById('aiResultLimit').value === 'all' 
                    ? "everything" 
                    : parseInt(document.getElementById('aiResultLimit').value),
                semantic_only: !aiAnalysis,
                report_type: document.getElementById('reportTypeFilter').value === 'ALL' ? null : document.getElementById('reportTypeFilter').value
            })
        });

        // Check if this search attempt is still the current one
        if (window.currentSearchAttempt !== searchAttemptId) {
            console.log(`Search attempt ${searchAttemptId} was superseded, aborting`);
            return;
        }

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Search request failed');
        }
        
        const data = await response.json();
        if (!data.task_id) {
            throw new Error('Invalid response: missing task ID');
        }
        activeTaskId = data.task_id;
        
        // Check again if this search attempt is still valid
        if (window.currentSearchAttempt !== searchAttemptId) {
            console.log(`Search attempt ${searchAttemptId} was superseded after getting task ID, cancelling task`);
            // Cancel the task we just created since it's no longer needed
            fetch(`/api/ai-search/${activeTaskId}/cancel`, { method: 'POST' })
                .then(() => console.log(`Cancelled superseded task ${activeTaskId}`))
                .catch(e => console.error(`Error cancelling superseded task: ${e}`));
            return;
        }
        
        document.getElementById('searchResults').innerHTML = `
            <div class="loading-indicator">
                <div class="loading-status">
                    <span class="status-icon"><i class="fas fa-search"></i></span>
                    <span>Initializing ${!aiAnalysis ? 'semantic' : 'AI'} search</span>
                    <span class="stage-badge">preparing</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill"></div>
                </div>
                <div class="progress-details">
                    <div class="stage-description">Preparing your search query...</div>
                </div>
            </div>
        `;

        // Start progress animation
        const progressFill = document.querySelector('.progress-fill');
        if (progressFill) {
            progressFill.style.width = '5%';
        }
        
        // Store the task ID in a data attribute for recovery
        const loadingIndicator = document.querySelector('.loading-indicator');
        if (loadingIndicator) {
            loadingIndicator.dataset.taskId = activeTaskId;
        }
        
        // Start polling for results
        pollingInterval = setInterval(async () => {
            // Check if this search is still active
            if (!isSearchInProgress || window.currentSearchAttempt !== searchAttemptId) {
                console.log(`Polling stopped: search no longer active (attempt ${searchAttemptId})`);
                clearInterval(pollingInterval);
                return;
            }
            
            // Check if we have a task ID to poll
            if (!activeTaskId) {
                console.log('No active task ID, stopping polling');
                clearInterval(pollingInterval);
                return;
            }
            
            try {
                const statusResponse = await fetch(`/api/ai-search/${activeTaskId}`);
                if (!statusResponse.ok) {
                    throw new Error('Failed to fetch search status');
                }
                const statusData = await statusResponse.json();
                
                console.log(`Status data received for task ${activeTaskId}:`, statusData);
                
                // Add this check to ensure the search is still active in the UI
                const loadingIndicator = document.querySelector('.loading-indicator');
                if (!loadingIndicator) {
                    console.log("Loading indicator no longer in DOM, stopping updates");
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    return;
                }
                
                // Check if this is still the current search attempt
                if (window.currentSearchAttempt !== searchAttemptId) {
                    console.log(`Polling detected superseded search attempt ${searchAttemptId}, stopping`);
                    clearInterval(pollingInterval);
                    return;
                }
                
                if (statusData.status === 'completed') {
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                    console.log(`Search completed in ${elapsed}s`);
                
                    // Complete progress bar
                    const progressFill = document.querySelector('.progress-fill');
                    if (progressFill) {
                        progressFill.style.width = '100%';
                    }
                
                
                    displayAiSearchResults(statusData.results);
                    searchButton.classList.remove('loading', 'stop-search');
                    searchButton.textContent = 'Search';
                    searchButton.disabled = false;
                    isSearchInProgress = false;
                    activeTaskId = null;
            } else if (statusData.status === 'error' || statusData.status === 'cancelled') {
                clearInterval(pollingInterval);
                pollingInterval = null;
                console.log('Search status:', statusData.status);
                
                if (statusData.status === 'cancelled') {
                    console.log('Search cancelled by user');
                    
                    // Check if we have partial results
                    if (statusData.partial_results && statusData.partial_results.length > 0) {
                        console.log(`Displaying ${statusData.partial_results.length} partial results from polling`);
                        
                        // Display partial results
                        displayAiSearchResults(statusData.partial_results);
                        
                        // Show a notification that these are partial results
                        const resultsDiv = document.getElementById('searchResults');
                        const resultCountDiv = resultsDiv.querySelector('.result-count');
                        if (resultCountDiv) {
                            resultCountDiv.style.backgroundColor = 'var(--warning-light)';
                            resultCountDiv.style.border = '1px solid var(--warning-border)';
                            resultCountDiv.innerHTML = `
                                <i class="fas fa-exclamation-triangle"></i> 
                                Search cancelled - showing ${statusData.partial_results.length} partial results
                                <button onclick="exportToCSV()" class="export-button">Export to CSV</button>
                            `;
                        }
                    } else {
                        // No partial results, show cancelled message
                        document.getElementById('searchResults').innerHTML = `
                            <div class="search-results-container">
                                <div class="result-count" style="background-color: var(--accent-light); border: 1px solid var(--accent-border);">
                                    <i class="fas fa-ban"></i> Search cancelled by user
                                </div>
                            </div>`;
                    }
                } else {
                    console.error('Search error:', statusData.error);
                    alert('Error performing AI search. Please try again or use semantic search mode.');
                }
                
                searchButton.classList.remove('loading', 'stop-search');
                searchButton.textContent = 'Search';
                searchButton.style.color = ''; // Reset text color
                searchButton.disabled = false;
                isSearchInProgress = false;
                activeTaskId = null;
            }
            // Handle different task statuses
            if (statusData.status === 'queued') {
                // Show queue position
                showQueuedStatus(statusData);
            } else if (statusData.status === 'running' || statusData.status === 'pending') {
                // Show progress with relevant_found count
                updateProgressDisplay(statusData, aiAnalysis);
            }
            } catch (error) {
                console.error('Polling error:', error);
                
                // Increment error counter
                window.pollingErrorCount = (window.pollingErrorCount || 0) + 1;
                
                // If we've had too many consecutive errors, stop polling and reset UI
                if (window.pollingErrorCount > 3) {
                    console.error('Too many polling errors, resetting search state');
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    
                    // Reset UI
                    searchButton.classList.remove('loading', 'stop-search');
                    searchButton.textContent = 'Search';
                    searchButton.disabled = false;
                    isSearchInProgress = false;
                    activeTaskId = null;
                    
                    // Show error message
                    document.getElementById('searchResults').innerHTML = `
                        <div class="search-results-container">
                            <div class="result-count" style="background-color: var(--error-light); border: 1px solid var(--error-border);">
                                <i class="fas fa-exclamation-circle"></i> Search failed: Connection error
                            </div>
                        </div>`;
                    
                    window.pollingErrorCount = 0;
                }
            }
        }, 1000); // Poll every second
        
    } catch (error) {
        console.error(`Search error in attempt ${searchAttemptId}:`, error);
        document.getElementById('searchResults').innerHTML = `
            <div class="search-results-container">
                <div class="result-count" style="background-color: var(--error-light); border: 1px solid var(--error-border);">
                    <i class="fas fa-exclamation-circle"></i> ${error.message || 'Error performing search. Please try again.'}
                </div>
            </div>`;
        searchButton.classList.remove('loading', 'stop-search');
        searchButton.textContent = 'Search';
        searchButton.disabled = false;
        isSearchInProgress = false;
        activeTaskId = null;
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }
}

function displayAiSearchResults(results) {
    const resultsDiv = document.getElementById('searchResults');
    const analysisDiv = document.getElementById('analysisResults');
    analysisDiv.innerHTML = ''; // Clear any existing analysis results
    
    // Hide the search placeholder
    document.getElementById('searchPlaceholder').style.display = 'none';
    
    // Count relevant results (score >= 0.50)
    const relevantResults = results.filter(r => (r.score || 0) >= 0.50);
    
    // Use the results as provided - pagination is now handled server-side
    const displayResults = results;

    if (displayResults.length === 0) {
        resultsDiv.innerHTML = `
            <div class="no-results">
                <p>No results found</p>
                <p style="font-size: 0.85em; color: var(--text-muted); margin-top: 8px;">
                    If this is a fresh installation, load example data first:<br>
                    <code style="background: var(--surface-hover); padding: 2px 6px; border-radius: 3px;">vetpathdb load-examples</code><br>
                    Then restart with: <code style="background: var(--surface-hover); padding: 2px 6px; border-radius: 3px;">vetpathdb serve --demo-db --skip-models</code>
                </p>
            </div>`;
        return;
    }
    
    let html = '<div class="search-results-container">';
    
    // Display result count and export button
    // Calculate number of relevant cases (score >= 0.50)
    const totalRelevant = relevantResults.length;
    const displayCount = displayResults.length;
    const totalCount = results.length;
    
    html += `<div class="result-count">
        Showing ${displayCount} cases (${totalRelevant} relevant out of ${totalCount} total matches)
        <button onclick="exportToCSV()" class="export-button">Export to CSV</button>
    </div>`;
    
    html += '<table><tr>';
    
    // Define columns based on search mode
    const columns = [
        ['score', 'Match Score'],
        ['case_id', 'Case ID'],
        ['species', 'Species'],
        ['date', 'Date'],
        ['pathologist', 'Pathologist'],
        ['report_type', 'Report Type']
    ];
    
    // Only add the appropriate analysis column based on search mode
    if (window.semanticOnly) {
        columns.push(['summary', 'Summary']);
    } else {
        columns.push(['reasoning', 'AI Analysis']);
    }
    
    // Always add actions column last
    columns.push(['actions', 'Actions']);
    
    // Add column headers
    columns.slice(0, -1).forEach(([key, label]) => {
        html += `<th onclick="sortTable('${key}')">${label}</th>`;
    });
    html += '<th>Actions</th></tr>';
    
    displayResults.forEach((r, index) => {
        const data = r.data || {};
        const animal = data.animal_details || {};
        const report = data.report_metadata || {};
        
        // Get animal details for tooltip
        const animalAge = animal.age ? `${animal.age} years` : 'N/A';
        const animalSex = animal.sex ? `${animal.sex}${animal.neutered ? ' (neutered)' : ''}` : 'N/A';
        
        // Determine score class
        const scoreValue = r.score || 0;
        let scoreClass = 'low';
        if (scoreValue >= 0.8) scoreClass = 'high';
        else if (scoreValue >= 0.5) scoreClass = 'medium';
        
        html += `
            <tr class="clickable-row" onclick="showCaseDetails(${index})" 
                title="Age: ${animalAge}&#13;Sex: ${animalSex}">
                <td data-score="${scoreClass}">${r.score ? r.score.toFixed(2) : 'N/A'}</td>
                <td>${r.case_id}</td>
                <td>
                    <strong>${animal.species || 'N/A'}</strong>
                    <span class="breed">${animal.breed || 'N/A'}</span>
                </td>
                <td>${report.date_received || 'N/A'}</td>
                <td>${(report.pathologists || []).join(', ') || 'N/A'}</td>
                <td>${report.report_type || 'N/A'}</td>
                <td>
                    ${window.semanticOnly 
                        ? ((data.summary || data.comment || 'No summary available'))
                        : (r.reasoning || 'No AI analysis available')
                    }
                    <span class="result-meta">
                        ${animalAge} • ${animalSex}
                    </span>
                </td>
                <td class="actions-cell">
                    <div class="action-buttons">
                        <button class="action-button copy-button" onclick="copyCaseSummary(${index}, event)" title="Copy case summary">
                            📋
                        </button>
                        <button class="action-button similar-button" onclick="event.stopPropagation(); findSimilarFromResult(${index})" title="Find similar cases">
                            🔍
                        </button>
                        <button class="action-button chat-button" onclick="event.stopPropagation(); openCaseChat(${index})" title="Ask AI about this case">
                            💬
                        </button>
                        <button class="action-button download-button" onclick="event.stopPropagation(); downloadCaseJson(${index})" title="Download case as JSON">
                            ⬇️
                        </button>
                    </div>
                </td>
            </tr>
        `;
    });
    
    html += '</table></div>';
    resultsDiv.innerHTML = html;
    
    // Update currentResults for case details functionality
    currentResults = results;
}

// Remove filter-related functions as they're no longer needed


function findSimilarFromResult(index) {
    const result = currentResults[index];
    const summary = result.data?.summary || result.data?.comment;
    
    if (!summary) {
        alert('No summary available for this case');
        return;
    }
    
    // Force semantic-only search
    const aiAnalysis = document.getElementById('aiAnalysis');
    aiAnalysis.checked = false;
    
    // Perform the search with the summary directly
    performAiSearch(summary);
}

function sortTable(column) {
    const headers = document.querySelectorAll('th');
    headers.forEach(header => {
        header.classList.remove('sort-asc', 'sort-desc');
    });

    if (currentSortColumn === column) {
        currentSortDirection = currentSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        currentSortColumn = column;
        currentSortDirection = 'asc';
    }

    const header = document.querySelector(`th:nth-child(${getColumnIndex(column) + 1})`);
    header.classList.add(`sort-${currentSortDirection}`);

    currentResults.sort((a, b) => {
        let valueA = getValueForColumn(a, column);
        let valueB = getValueForColumn(b, column);

        if (typeof valueA === 'string') {
            valueA = valueA.toLowerCase();
            valueB = valueB.toLowerCase();
        }

        if (valueA < valueB) return currentSortDirection === 'asc' ? -1 : 1;
        if (valueA > valueB) return currentSortDirection === 'asc' ? 1 : -1;
        return 0;
    });

    displaySearchResults(currentResults);
}

async function findSimilarCases() {
    const caseId = document.getElementById('similarCaseId').value.trim();
    if (!caseId) {
        alert('Please enter a Case ID');
        return;
    }

    // Immediately hide the search placeholder
    document.getElementById('searchPlaceholder').style.display = 'none';

    try {
        // First fetch the case summary
        const summaryResponse = await fetch(`/api/case/${caseId}`);
        if (!summaryResponse.ok) {
            throw new Error('Case not found');
        }
        const caseData = await summaryResponse.json();
        const summary = caseData.case?.data?.summary || caseData.case?.data?.comment;
        
        if (!summary) {
            alert('No summary found for this case');
            return;
        }
        
        // Force semantic-only search
        const aiAnalysis = document.getElementById('aiAnalysis');
        aiAnalysis.checked = false;
        
        // Perform the search with the summary directly
        performAiSearch(summary);
        
    } catch (error) {
        console.error('Error finding similar cases:', error);
        alert('Error finding similar cases. Please check the Case ID and try again.');
    }
}

// Add a recovery function to handle stuck UI states
function recoverFromStuckState() {
    console.log('Attempting to recover from stuck state');
    
    // Clear any polling intervals
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
    
    // Reset button state
    const searchButton = document.querySelector('.ai-controls button');
    if (searchButton) {
        searchButton.classList.remove('loading', 'stop-search');
        searchButton.textContent = 'Search';
        searchButton.disabled = false;
    }
    
    // Reset search state
    isSearchInProgress = false;
    
    // Try to cancel any active task
    if (activeTaskId) {
        fetch(`/api/ai-search/${activeTaskId}/cancel`, { method: 'POST' })
            .then(() => console.log(`Cancelled task ${activeTaskId} during recovery`))
            .catch(e => console.error(`Error cancelling task during recovery: ${e}`));
        activeTaskId = null;
    }
    
    // Check for a task ID in the loading indicator
    const loadingIndicator = document.querySelector('.loading-indicator');
    if (loadingIndicator && loadingIndicator.dataset.taskId) {
        const taskId = loadingIndicator.dataset.taskId;
        console.log(`Found task ID ${taskId} in loading indicator, attempting to cancel`);
        fetch(`/api/ai-search/${taskId}/cancel`, { method: 'POST' })
            .then(() => console.log(`Cancelled task ${taskId} from loading indicator`))
            .catch(e => console.error(`Error cancelling task from loading indicator: ${e}`));
    }
    
    // Show recovery message
    document.getElementById('searchResults').innerHTML = `
        <div class="search-results-container">
            <div class="result-count" style="background-color: var(--accent-light); border: 1px solid var(--accent-border);">
                <i class="fas fa-sync"></i> Search interface reset
            </div>
        </div>`;
}

// Add a global error handler to catch and recover from unexpected errors
window.addEventListener('error', function(event) {
    console.error('Global error caught:', event.error);
    
    // If we're in a search state, try to recover
    if (isSearchInProgress) {
        console.log('Error occurred during search, attempting recovery');
        recoverFromStuckState();
    }
});

// Add a double-click handler to the search button for emergency recovery
document.addEventListener('DOMContentLoaded', function() {
    const searchButton = document.querySelector('.ai-controls button');
    if (searchButton) {
        searchButton.addEventListener('dblclick', function(event) {
            console.log('Search button double-clicked, forcing recovery');
            recoverFromStuckState();
        });
    }
});

function getValueForColumn(result, column) {
    const data = result.data || {};
    const animal = data.animal_details || {};
    const report = data.report_metadata || {};
    const histo = data.histopathology || {};

    switch(column) {
        case 'score':
            return result.score || 0;
        case 'case_id':
            return result.case_id || '';
        case 'species':
            return animal.species || '';
        case 'date':
            return report.date_received || '';
        case 'diagnosis':
            return histo.diagnosis || '';
        case 'pathologist':
            return (report.pathologists || []).join(', ');
        case 'report_type':
            return report.report_type || '';
        default:
            return '';
    }
}

function insertExample(text) {
    const searchInput = document.getElementById('aiSearchQuery');
    searchInput.value = text;
    searchInput.focus();
    // Hide the placeholder
    document.getElementById('searchPlaceholder').style.display = 'none';
}

// View partial results while search is running
async function viewPartialResults(taskId, relevantCount) {
    try {
        // Fetch the current task status to get partial results
        const response = await fetch(`/api/ai-search/${taskId}`);
        if (!response.ok) {
            throw new Error('Failed to fetch partial results');
        }

        const taskData = await response.json();

        // Check if we have results
        if (!taskData.results || taskData.results.length === 0) {
            alert('No results available yet. Please wait for the search to find relevant cases.');
            return;
        }

        // Store results globally so case details work
        window.currentResults = taskData.results;

        // Set the search box to show the query being viewed (with partial results indicator)
        const searchInput = document.getElementById('aiSearchQuery');
        if (searchInput && taskData.query) {
            searchInput.value = taskData.query + ' (viewing partial results)';
        }

        // Use the AI search results display function (handles nested data structure)
        if (typeof displayAiSearchResults === 'function') {
            displayAiSearchResults(taskData.results);

            // Scroll to results
            const resultsDiv = document.getElementById('searchResults');
            if (resultsDiv) {
                resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        } else {
            console.error('displayAiSearchResults function not found');
            alert('Unable to display results. Please refresh the page.');
        }

    } catch (error) {
        console.error('Error viewing partial results:', error);
        alert(`Failed to load partial results: ${error.message}`);
    }
}
