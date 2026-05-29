// UI Initialization and Event Handlers
async function loadDatabaseInsights() {
    try {
        // Fetch basic stats first
        const response = await fetch('/api/stats');
        const data = await response.json();
        
        // Update basic stat cards
        const statsDiv = document.getElementById('basicStats');
        // Calculate percentages for tumor distribution
        const tumorDistribution = data.tumor_distribution || [];
        const tumorCases = tumorDistribution.find(d => d?._id)?.count || 0;
        const nonTumorCases = tumorDistribution.find(d => !d?._id)?.count || 0;
        const tumorPercentage = data.total_cases ? ((tumorCases / data.total_cases) * 100).toFixed(1) : '0.0';
        
        // Create stat cards for the new design - compact version with fewer cards
        statsDiv.innerHTML = `
            <div class="stat-card compact">
                <div class="stat-value">${(data.total_cases || 0).toLocaleString()}</div>
                <div class="stat-label">Total Cases</div>
            </div>
            <div class="stat-card compact">
                <div class="stat-value">${data.unique_species || 0}</div>
                <div class="stat-label">Species</div>
            </div>
        `;
        
        // Update species distribution chart
        if (data.species_distribution && data.species_distribution.length > 0) {
            const speciesLabels = data.species_distribution.slice(0, 5).map(s => s._id || 'Unknown');
            const speciesCounts = data.species_distribution.slice(0, 5).map(s => s.count);
            
            const ctx = document.getElementById('speciesChart').getContext('2d');
            new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: speciesLabels,
                    datasets: [{
                        data: speciesCounts,
                        backgroundColor: [
                            '#5b5fb6', '#7d56d9', '#3b82f6', '#0ea5e9', '#06b6d4'
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                boxWidth: 12,
                                font: {
                                    size: 10
                                }
                            }
                        }
                    }
                }
            });
            
            // Update top species text
            document.getElementById('topSpecies').textContent = 
                data.species_distribution.slice(0, 3)
                    .map(s => `${s._id || 'Unknown'} (${s.count})`)
                    .join(', ');
        }
        
        // Update trends chart
        if (data.yearly_cases && data.yearly_cases.length > 0) {
            // Use all years instead of just the last 5
            const years = data.yearly_cases.map(y => y._id);
            const counts = data.yearly_cases.map(y => y.count);
            
            const trendsCtx = document.getElementById('trendsChart').getContext('2d');
            new Chart(trendsCtx, {
                type: 'line',
                data: {
                    labels: years,
                    datasets: [{
                        label: 'Cases',
                        data: counts,
                        borderColor: '#5b5fb6',
                        backgroundColor: 'rgba(91, 95, 182, 0.1)',
                        tension: 0.3,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                font: {
                                    size: 10
                                }
                            }
                        },
                        x: {
                            ticks: {
                                font: {
                                    size: 10
                                }
                            }
                        }
                    }
                }
            });
            
            // Calculate trend
            const lastTwoYears = data.yearly_cases.slice(-2);
            if (lastTwoYears.length === 2) {
                const currentYear = lastTwoYears[1];
                const previousYear = lastTwoYears[0];
                const percentChange = ((currentYear.count - previousYear.count) / previousYear.count * 100).toFixed(1);
                
                let trendText = '';
                if (percentChange > 0) {
                    trendText = `<span style="color: #22c55e">↑ ${percentChange}%</span> increase in cases from ${previousYear._id} to ${currentYear._id}`;
                } else if (percentChange < 0) {
                    trendText = `<span style="color: #ef4444">↓ ${Math.abs(percentChange)}%</span> decrease in cases from ${previousYear._id} to ${currentYear._id}`;
                } else {
                    trendText = `No change in case volume from ${previousYear._id} to ${currentYear._id}`;
                }
                
                document.getElementById('trendSummary').innerHTML = `
                    <p>${trendText}</p>
                    <p>Average yearly cases: ${Math.round(data.yearly_cases.reduce((sum, y) => sum + y.count, 0) / data.yearly_cases.length)}</p>
                `;
            }
        }
        
        // Update diagnosis distribution
        if (data.diagnosis_distribution) {
            const tumorCount = data.diagnosis_distribution.tumor || 0;
            const inflammatoryCount = data.diagnosis_distribution.inflammatory || 0;
            const degenerativeCount = data.diagnosis_distribution.degenerative || 0;
            const total = tumorCount + inflammatoryCount + degenerativeCount;
            
            if (total > 0) {
                const tumorPercent = (tumorCount / total * 100).toFixed(1);
                const inflammatoryPercent = (inflammatoryCount / total * 100).toFixed(1);
                const degenerativePercent = (degenerativeCount / total * 100).toFixed(1);
                
                document.getElementById('tumorBar').style.width = `${tumorPercent}%`;
                document.getElementById('inflammatoryBar').style.width = `${inflammatoryPercent}%`;
                document.getElementById('degenerativeBar').style.width = `${degenerativePercent}%`;
                
                document.getElementById('tumorValue').textContent = `${tumorPercent}%`;
                document.getElementById('inflammatoryValue').textContent = `${inflammatoryPercent}%`;
                document.getElementById('degenerativeValue').textContent = `${degenerativePercent}%`;
            }
            
            // Update top diagnoses
            if (data.top_diagnoses && data.top_diagnoses.length > 0) {
                const topDiagnosesHtml = data.top_diagnoses.slice(0, 5).map(d => 
                    `<div class="top-item">
                        <span class="item-label">${d._id || 'Unknown'}</span>
                        <span class="item-value">${d.count} cases</span>
                    </div>`
                ).join('');
            
                document.getElementById('topDiagnoses').innerHTML = topDiagnosesHtml;
            }
        
        }
        
        // Update pathologists chart and list
        if (data.top_pathologists && data.top_pathologists.length > 0) {
            const pathologistLabels = data.top_pathologists.slice(0, 5).map(p => p._id || 'Unknown');
            const pathologistCounts = data.top_pathologists.slice(0, 5).map(p => p.count);
        
            const pathCtx = document.getElementById('pathologistsChart').getContext('2d');
            new Chart(pathCtx, {
                type: 'bar',
                data: {
                    labels: pathologistLabels,
                    datasets: [{
                        label: 'Cases',
                        data: pathologistCounts,
                        backgroundColor: [
                            '#5b5fb6', '#7d56d9', '#3b82f6', '#0ea5e9', '#06b6d4'
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                font: {
                                    size: 10
                                }
                            }
                        },
                        x: {
                            ticks: {
                                font: {
                                    size: 10
                                }
                            }
                        }
                    }
                }
            });
        
            // Update top pathologists list
            const topPathologistsHtml = data.top_pathologists.slice(0, 10).map(p => 
                `<div class="top-item">
                    <span class="item-label">${p._id || 'Unknown'}</span>
                    <span class="item-value">${p.count} cases</span>
                </div>`
            ).join('');
        
            document.getElementById('topPathologists').innerHTML = topPathologistsHtml;
        } else {
            // Handle empty pathologists data
            const pathCtx = document.getElementById('pathologistsChart').getContext('2d');
            new Chart(pathCtx, {
                type: 'bar',
                data: {
                    labels: ['No data available'],
                    datasets: [{
                        label: 'Cases',
                        data: [0],
                        backgroundColor: ['#e9ecef'],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                font: {
                                    size: 10
                                }
                            }
                        },
                        x: {
                            ticks: {
                                font: {
                                    size: 10
                                }
                            }
                        }
                    }
                }
            });
            
            document.getElementById('topPathologists').innerHTML = `
                <div class="top-item">
                    <span class="item-label">No pathologist data available</span>
                    <span class="item-value">-</span>
                </div>`;
        }
        
        // Update case type distribution chart
        if (data.case_type_distribution && data.case_type_distribution.length > 0) {
            const caseTypeLabels = data.case_type_distribution.map(t => t._id || 'Unknown');
            const caseTypeCounts = data.case_type_distribution.map(t => t.count);
            
            const typeCtx = document.getElementById('caseTypeChart').getContext('2d');
            new Chart(typeCtx, {
                type: 'doughnut',
                data: {
                    labels: caseTypeLabels,
                    datasets: [{
                        data: caseTypeCounts,
                        backgroundColor: [
                            '#ff6b6b', // Red for PM
                            '#4ecdc4', // Teal for SP  
                            '#45b7d1', // Blue for IH
                            '#f9ca24', // Yellow for CY
                            '#6c5ce7'  // Purple for Unknown
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                boxWidth: 12,
                                font: {
                                    size: 10
                                }
                            }
                        }
                    }
                }
            });
            
            // Update top case types list
            const topCaseTypesHtml = data.case_type_distribution.map(t => 
                `<div class="top-item">
                    <span class="item-label">${t._id || 'Unknown'}</span>
                    <span class="item-value">${t.count} cases</span>
                </div>`
            ).join('');
            
            document.getElementById('topCaseTypes').innerHTML = topCaseTypesHtml;
        } else {
            // Handle empty case type data
            const typeCtx = document.getElementById('caseTypeChart').getContext('2d');
            new Chart(typeCtx, {
                type: 'doughnut',
                data: {
                    labels: ['No data available'],
                    datasets: [{
                        data: [1],
                        backgroundColor: ['#e9ecef'],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                boxWidth: 12,
                                font: {
                                    size: 10
                                }
                            }
                        }
                    }
                }
            });
            
            document.getElementById('topCaseTypes').innerHTML = `
                <div class="top-item">
                    <span class="item-label">No case type data available</span>
                    <span class="item-value">-</span>
                </div>`;
        }
        
        // Update recent activity
        if (data.recent_activity) {
            document.getElementById('weeklyAdditions').textContent = data.recent_activity.weekly_additions || 0;
        }
        
    } catch (error) {
        console.error('Error loading database insights:', error);
        const statsDiv = document.getElementById('basicStats');
        statsDiv.innerHTML = '<p>Error loading statistics</p>';
    }
}

// Tab switching functionality
function setupInsightTabs() {
    // Hide pathologist tab as it's currently broken
    const pathologistTab = document.querySelector('.insight-tab[data-tab="pathologists"]');
    if (pathologistTab) {
        pathologistTab.style.display = 'none';
    }
    
    const tabs = document.querySelectorAll('.insight-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Remove active class from all tabs and panes
            document.querySelectorAll('.insight-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.insight-pane').forEach(p => p.classList.remove('active'));
            
            // Add active class to clicked tab
            tab.classList.add('active');
            
            // Show corresponding pane
            const paneId = `${tab.dataset.tab}-pane`;
            document.getElementById(paneId).classList.add('active');
        });
    });
}

async function populateReportTypeDropdown() {
    // Fetch registered schemas from the backend and hydrate both the custom
    // dropdown's <div data-value="..."> entries and the hidden <select> that
    // aiSearchManager reads. The "All Reports" entry is already in the DOM;
    // everything else is added here.
    try {
        const response = await fetch('/api/schemas');
        if (!response.ok) return;
        const schemas = await response.json();

        const itemsDiv = document.querySelector('#reportTypeWrapper .select-items');
        const nativeSelect = document.getElementById('reportTypeFilter');
        if (!itemsDiv || !nativeSelect) return;

        schemas.forEach(s => {
            const code = s.code || '';
            if (!code || code === 'ALL') return;
            const label = s.label_plural || `${code} Reports`;
            const icon = s.icon || 'fa-file-medical';

            const item = document.createElement('div');
            item.setAttribute('data-value', code);
            item.innerHTML = `<i class="fas ${icon}"></i> ${label}`;
            itemsDiv.appendChild(item);

            const opt = document.createElement('option');
            opt.value = code;
            opt.textContent = label;
            nativeSelect.appendChild(opt);
        });
    } catch (err) {
        console.warn('Could not populate report type dropdown from /api/schemas:', err);
    }
}

document.addEventListener('DOMContentLoaded', async function() {
    // Hydrate the report-type dropdown before wiring up its click handlers,
    // otherwise the dynamically-added items won't get interactivity.
    await populateReportTypeDropdown();
    loadDatabaseInsights();
    setupInsightTabs();
    setupKeyboardShortcuts();
    setupCustomSelect();
    setupModalHandlers();

    // Initialize current results array
    window.currentResults = [];
    
    // Initialize sort state
    window.currentSortColumn = '';
    window.currentSortDirection = 'asc';
    
    // Add enter key handler for search
    document.getElementById('aiSearchQuery').addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault(); // Prevent new line
            performAiSearch();
        }
    });
});


function setupCustomSelect() {
    // Initialize all custom select elements
    const customSelects = ['reportTypeWrapper', 'resultLimitWrapper'];

    customSelects.forEach(wrapperId => {
        const wrapper = document.getElementById(wrapperId);
        if (!wrapper) return;

        const select = wrapper.querySelector('select');
        const selectedDiv = wrapper.querySelector('.select-selected');
        const itemsDiv = wrapper.querySelector('.select-items');
        const isEditable = wrapper.classList.contains('editable-select');
        const inputField = isEditable ? wrapper.querySelector('.select-input') : null;

        // Handle editable input field
        if (isEditable && inputField) {
            // Update select value when input changes
            inputField.addEventListener('input', function(e) {
                const value = this.value.trim();
                select.value = value;
                selectedDiv.setAttribute('data-value', value);

                // Trigger change event
                const event = new Event('change');
                select.dispatchEvent(event);
            });

            // Prevent dropdown from opening when clicking on input
            inputField.addEventListener('click', function(e) {
                e.stopPropagation();
            });

            // Allow Enter key to confirm value
            inputField.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.blur();
                    itemsDiv.classList.add('select-hide');
                    selectedDiv.classList.remove('select-arrow-active');
                }
            });
        }

        selectedDiv.addEventListener('click', function(e) {
            // Don't open dropdown if clicking directly on input
            if (isEditable && e.target === inputField) {
                return;
            }

            e.stopPropagation();
            // Close any other open selects
            document.querySelectorAll('.select-items').forEach(item => {
                if (item !== itemsDiv) {
                    item.classList.add('select-hide');
                }
            });
            document.querySelectorAll('.select-selected').forEach(selected => {
                if (selected !== this) {
                    selected.classList.remove('select-arrow-active');
                }
            });

            // Toggle this select
            this.classList.toggle('select-arrow-active');
            itemsDiv.classList.toggle('select-hide');
        });

        itemsDiv.querySelectorAll('div').forEach(item => {
            item.addEventListener('click', function(e) {
                e.stopPropagation();
                const value = this.getAttribute('data-value');
                select.value = value;

                // Update display based on whether it's editable
                if (isEditable && inputField) {
                    inputField.value = value;
                } else {
                    selectedDiv.innerHTML = this.innerHTML;
                }

                selectedDiv.setAttribute('data-value', value);
                itemsDiv.classList.add('select-hide');
                selectedDiv.classList.remove('select-arrow-active');

                // Trigger change event on the original select
                const event = new Event('change');
                select.dispatchEvent(event);
            });
        });
    });

    // Global click handler to close all selects when clicking elsewhere
    document.addEventListener('click', function() {
        document.querySelectorAll('.select-items').forEach(item => {
            item.classList.add('select-hide');
        });
        document.querySelectorAll('.select-selected').forEach(selected => {
            selected.classList.remove('select-arrow-active');
        });
    });
}

function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        // Alt + F to focus on main search box
        if (e.altKey && e.key === 'f') {
            e.preventDefault();
            document.getElementById('aiSearchQuery').focus();
        }
        
        // Alt + number shortcuts for analysis
        if (e.altKey) {
            switch(e.key) {
                case '1':
                    e.preventDefault();
                    showMorphologicalAnalysis();
                    break;
                case '2':
                    e.preventDefault();
                    showIHCPatterns();
                    break;
                case '3':
                    e.preventDefault();
                    showBreedPatterns();
                    break;
                case '4':
                    e.preventDefault();
                    showDiagnosticTimeline();
                    break;
                case '5':
                    e.preventDefault();
                    showDatabaseExplorer();
                    break;
            }
        }
    });
}
