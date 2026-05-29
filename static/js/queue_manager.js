/**
 * Queue Manager for AI Search Task Queue
 * Handles queue panel display, updates, and task management
 */

// Global variables for queue management
let queueRefreshInterval = null;
let isQueuePanelOpen = false;

/**
 * Open the queue panel and start refreshing
 */
function openQueuePanel() {
    const modal = document.getElementById('queueModal');
    modal.style.display = 'block';
    isQueuePanelOpen = true;

    // Load queue data immediately
    refreshQueueData();

    // Start periodic refresh (every 3 seconds)
    if (queueRefreshInterval) {
        clearInterval(queueRefreshInterval);
    }
    queueRefreshInterval = setInterval(refreshQueueData, 3000);
}

/**
 * Close the queue panel and stop refreshing
 */
function closeQueuePanel() {
    const modal = document.getElementById('queueModal');
    modal.style.display = 'none';
    isQueuePanelOpen = false;

    // Stop periodic refresh
    if (queueRefreshInterval) {
        clearInterval(queueRefreshInterval);
        queueRefreshInterval = null;
    }
}

/**
 * Fetch and display queue data from API
 */
async function refreshQueueData() {
    try {
        const response = await fetch('/api/ai-search-queue');
        if (!response.ok) {
            console.error('Failed to fetch queue data:', response.statusText);
            return;
        }

        const data = await response.json();

        // Update stats
        document.getElementById('queuedCount').textContent = data.stats.queued_count;
        document.getElementById('runningCount').textContent = data.stats.running_count;
        document.getElementById('recentCount').textContent = data.recent.length;

        // Update queue badge on button
        updateQueueBadge(data.stats.total_active);

        // Update task lists
        updateQueuedTasks(data.queued);
        updateRunningTasks(data.running);
        updateRecentTasks(data.recent);

    } catch (error) {
        console.error('Error refreshing queue data:', error);
    }
}

/**
 * Update the queue badge on the Queue button
 */
function updateQueueBadge(count) {
    const badge = document.getElementById('queueBadge');
    if (count > 0) {
        badge.textContent = count;
        badge.style.display = 'inline-block';
    } else {
        badge.style.display = 'none';
    }
}

/**
 * Update the queued tasks list
 */
function updateQueuedTasks(tasks) {
    const container = document.getElementById('queuedTasks');

    if (!tasks || tasks.length === 0) {
        container.innerHTML = '<p class="no-tasks">No tasks in queue</p>';
        return;
    }

    container.innerHTML = tasks.map(task => createTaskCard(task, 'queued')).join('');
}

/**
 * Update the running tasks list
 */
function updateRunningTasks(tasks) {
    const container = document.getElementById('runningTasks');

    if (!tasks || tasks.length === 0) {
        container.innerHTML = '<p class="no-tasks">No running tasks</p>';
        return;
    }

    container.innerHTML = tasks.map(task => createTaskCard(task, 'running')).join('');
}

/**
 * Update the recent completed tasks list
 */
function updateRecentTasks(tasks) {
    const container = document.getElementById('recentTasks');

    if (!tasks || tasks.length === 0) {
        container.innerHTML = '<p class="no-tasks">No recent tasks</p>';
        return;
    }

    container.innerHTML = tasks.map(task => createTaskCard(task, 'recent')).join('');
}

/**
 * Create HTML for a task card
 */
function createTaskCard(task, category) {
    const timeAgo = getTimeAgo(task.created_at);
    const statusClass = `status-${task.status}`;

    // Determine search mode
    const searchMode = task.semantic_only ? 'Semantic' : 'AI Analysis';
    const searchModeIcon = task.semantic_only ? 'fa-search' : 'fa-brain';

    // Determine depth
    let depthText = 'Unknown';
    if (task.depth === 'everything' || task.depth === 'Everything') {
        depthText = 'Everything';
    } else if (typeof task.depth === 'number') {
        depthText = `Top ${task.depth.toLocaleString()}`;
    }

    let actionsHtml = '';
    if (category === 'queued') {
        actionsHtml = `
            <span class="queue-position-badge">#${task.queue_position || '?'}</span>
            <button class="cancel-btn" onclick="cancelTask('${task.task_id}')">
                <i class="fas fa-times"></i> Cancel
            </button>
        `;
    } else if (category === 'running') {
        // Show "View Partial" button if there are relevant results
        const viewPartialBtn = task.relevant_found && task.relevant_found > 0 ?
            `<button class="view-btn" onclick="viewTaskPartialResults('${task.task_id}')">
                <i class="fas fa-eye"></i> ${task.relevant_found}
            </button>` : '';

        actionsHtml = `
            ${viewPartialBtn}
            <button class="cancel-btn" onclick="cancelTask('${task.task_id}')">
                <i class="fas fa-times"></i>
            </button>
        `;
    } else if (category === 'recent' && task.status === 'completed') {
        const resultsCount = task.relevant_found || task.results_count || 0;
        actionsHtml = `
            <button class="view-btn" onclick="viewTaskResults('${task.task_id}')">
                <i class="fas fa-eye"></i> View${resultsCount > 0 ? ` (${resultsCount})` : ''}
            </button>
        `;
    }

    let progressHtml = '';
    if (category === 'running' && task.progress !== undefined) {
        const progress = task.progress || 0;
        const processed = task.processed_cases || 0;
        const total = task.total_cases || 0;
        const relevantFound = task.relevant_found || 0;

        progressHtml = `
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: ${progress}%"></div>
            </div>
            <div class="progress-text">
                <span>${progress}%</span>
                <span>${processed.toLocaleString()}/${total.toLocaleString()} cases</span>
            </div>
        `;
    }

    // Build metadata section
    let metaHtml = '';
    const metaItems = [];

    // Add results badge for completed tasks
    if (category === 'recent' && task.status === 'completed' && task.relevant_found) {
        metaItems.push(`<span class="results-badge"><i class="fas fa-check-circle"></i> ${task.relevant_found} results</span>`);
    }

    // Add search mode and depth
    metaItems.push(`<span class="depth-badge"><i class="fas ${searchModeIcon}"></i> ${searchMode}</span>`);
    metaItems.push(`<span class="depth-badge"><i class="fas fa-layer-group"></i> ${depthText}</span>`);

    // Add time and task ID
    metaItems.push(`<span class="task-meta-item"><i class="fas fa-clock"></i> ${timeAgo}</span>`);
    metaItems.push(`<span class="task-meta-item"><i class="fas fa-hashtag"></i> ${task.task_id.substring(0, 8)}</span>`);

    if (metaItems.length > 0) {
        metaHtml = `<div class="task-meta">${metaItems.join('')}</div>`;
    }

    return `
        <div class="task-card">
            <div class="task-header">
                <div class="task-query" title="${escapeHtml(task.query)}">
                    ${escapeHtml(truncate(task.query, 70))}
                </div>
                <div class="task-actions">
                    ${actionsHtml}
                </div>
            </div>
            <div class="task-info">
                <div class="task-info-item">
                    <span class="task-status ${statusClass}">${task.status}</span>
                </div>
            </div>
            ${metaHtml}
            ${progressHtml}
        </div>
    `;
}

/**
 * Cancel a task
 */
async function cancelTask(taskId) {
    if (!confirm('Are you sure you want to cancel this task?')) {
        return;
    }

    try {
        const response = await fetch(`/api/ai-search-queue/${taskId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error(`Failed to cancel task: ${response.statusText}`);
        }

        // Refresh queue data immediately
        await refreshQueueData();

        console.log(`Task ${taskId} cancelled successfully`);
    } catch (error) {
        console.error('Error cancelling task:', error);
        alert(`Failed to cancel task: ${error.message}`);
    }
}

/**
 * View task results (navigate to results)
 */
async function viewTaskResults(taskId) {
    // Close queue panel
    closeQueuePanel();

    console.log(`Viewing results for task: ${taskId}`);

    try {
        // Fetch the task data from the API
        const response = await fetch(`/api/ai-search/${taskId}`);
        if (!response.ok) {
            const errorText = await response.text();
            console.error('API error response:', errorText);
            throw new Error(`Failed to fetch task results: ${response.statusText}`);
        }

        const taskData = await response.json();
        console.log('Task data received:', taskData);

        // Check if we have results
        if (!taskData.results || taskData.results.length === 0) {
            console.warn('No results in task data');
            alert('This search has no results to display.');
            return;
        }

        console.log(`Displaying ${taskData.results.length} results for query: ${taskData.query}`);

        // Store results globally so case details work
        if (typeof currentResults !== 'undefined') {
            window.currentResults = taskData.results;
        }

        // Set the search box to show the query that was used for this search
        const searchInput = document.getElementById('aiSearchQuery');
        if (searchInput && taskData.query) {
            searchInput.value = taskData.query;
            console.log('Search box populated with query:', taskData.query);
        }

        // Display the results using the AI search results function (handles nested data structure)
        if (typeof displayAiSearchResults === 'function') {
            displayAiSearchResults(taskData.results);
            console.log('displayAiSearchResults called successfully');

            // Scroll to results
            const resultsDiv = document.getElementById('searchResults');
            if (resultsDiv) {
                resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
                console.log('Scrolled to results');
            }
        } else {
            console.error('displayAiSearchResults function not found');
            alert('Unable to display results. Please refresh the page.');
        }
    } catch (error) {
        console.error('Error viewing task results:', error);
        alert(`Failed to load results: ${error.message}`);
    }
}

/**
 * View partial results for a running task from queue panel
 */
async function viewTaskPartialResults(taskId) {
    try {
        // Close the queue panel
        closeQueuePanel();

        // Call the viewPartialResults function from search_logic.js
        if (typeof viewPartialResults === 'function') {
            // Fetch task data to get relevant count
            const response = await fetch(`/api/ai-search/${taskId}`);
            if (response.ok) {
                const data = await response.json();
                await viewPartialResults(taskId, data.relevant_found || 0);
            }
        } else {
            console.error('viewPartialResults function not found');
            alert('Unable to view partial results. Please refresh the page.');
        }
    } catch (error) {
        console.error('Error viewing partial results from queue:', error);
        alert(`Failed to view partial results: ${error.message}`);
    }
}

/**
 * Get human-readable time ago string
 */
function getTimeAgo(dateString) {
    if (!dateString) return 'Unknown';

    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

/**
 * Truncate string to max length
 */
function truncate(str, maxLength) {
    if (!str) return '';
    if (str.length <= maxLength) return str;
    return str.substring(0, maxLength) + '...';
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Update queue badge periodically (even when panel is closed)
 */
async function updateQueueBadgeOnly() {
    try {
        const response = await fetch('/api/ai-search-queue');
        if (response.ok) {
            const data = await response.json();
            updateQueueBadge(data.stats.total_active);
        }
    } catch (error) {
        // Silently fail - just a badge update
    }
}

// Update badge every 10 seconds even when panel is closed
setInterval(updateQueueBadgeOnly, 10000);

// Close modal if user clicks outside of it
window.onclick = function(event) {
    const modal = document.getElementById('queueModal');
    if (event.target === modal) {
        closeQueuePanel();
    }
};
