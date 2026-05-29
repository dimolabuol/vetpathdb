// Chart creation and visualization functions

// Store chart instances for high-res export
const chartInstances = {};

// Helper function to download chart as high-resolution PNG
function downloadChartAsTiff(canvasId, filename) {
    const originalCanvas = document.getElementById(canvasId);
    if (!originalCanvas) {
        console.error('Canvas not found:', canvasId);
        return;
    }

    // Create export canvas with white background
    const exportCanvas = document.createElement('canvas');
    exportCanvas.width = originalCanvas.width;
    exportCanvas.height = originalCanvas.height;

    const exportCtx = exportCanvas.getContext('2d');

    // Fill white background
    exportCtx.fillStyle = '#ffffff';
    exportCtx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);

    // Draw the chart on top
    exportCtx.drawImage(originalCanvas, 0, 0);

    // Download
    exportCanvas.toBlob(function(blob) {
        if (!blob) {
            console.error('Failed to create blob for chart export');
            return;
        }
        const link = document.createElement('a');
        link.download = filename + '_highres.png';
        link.href = URL.createObjectURL(blob);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
    }, 'image/png', 1.0);
}

// Helper function to add download button to a chart container
function addDownloadButton(canvasId, filename) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const container = canvas.parentElement;

    // Check if button already exists
    if (container.querySelector('.chart-download-btn')) return;

    const btn = document.createElement('button');
    btn.className = 'chart-download-btn';
    btn.innerHTML = '<i class="fas fa-download"></i> Download High-Res';
    btn.title = 'Download 2x resolution PNG for publication';
    btn.onclick = function() {
        downloadChartAsTiff(canvasId, filename);
    };

    // Insert button before the canvas
    container.insertBefore(btn, canvas);
}

function createSummaryCharts(analysis) {
    // Prepare data for size summary
    const sizeData = {
        small: 0,
        medium: 0,
        large: 0,
        variable: 0
    };
    
    // Prepare data for shape summary
    const shapeData = {
        round: 0,
        polygonal: 0,
        spindle: 0,
        pleomorphic: 0
    };
    
    // Aggregate data across all tumor types
    analysis.forEach(tumor => {
        Object.entries(tumor.features.size).forEach(([size, data]) => {
            sizeData[size] += data.count;
        });
        Object.entries(tumor.features.shape).forEach(([shape, data]) => {
            shapeData[shape] += data.count;
        });
    });
    
    // Create size summary chart
    const sizeCtx = document.getElementById('sizeSummaryChart').getContext('2d');
    new Chart(sizeCtx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(sizeData).map(s => s.charAt(0).toUpperCase() + s.slice(1)),
            datasets: [{
                data: Object.values(sizeData),
                backgroundColor: [
                    '#FF6384',
                    '#36A2EB',
                    '#FFCE56',
                    '#4BC0C0'
                ]
            }]
        },
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: 'Overall Cell Size Distribution'
                },
                legend: {
                    position: 'bottom'
                }
            }
        }
    });
    
    // Create shape summary chart
    const shapeCtx = document.getElementById('shapeSummaryChart').getContext('2d');
    new Chart(shapeCtx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(shapeData).map(s => s.charAt(0).toUpperCase() + s.slice(1)),
            datasets: [{
                data: Object.values(shapeData),
                backgroundColor: [
                    '#FF9F40',
                    '#4BC0C0',
                    '#36A2EB',
                    '#FF6384'
                ]
            }]
        },
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: 'Overall Cell Shape Distribution'
                },
                legend: {
                    position: 'bottom'
                }
            }
        }
    });
}

function createIHCSummaryCharts(patternsData) {
    try {
        // Prepare data for marker distribution chart
        const markerCounts = {};
        Object.values(patternsData).flat().forEach(marker => {
            if (!markerCounts[marker.marker]) {
                markerCounts[marker.marker] = 0;
            }
            markerCounts[marker.marker] += marker.total_cases;
        });

        // Sort markers by count and get top 10
        const topMarkers = Object.entries(markerCounts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10);

        // Create marker distribution chart
        const markerCtx = document.getElementById('markerDistributionChart');
        if (!markerCtx) {
            console.error('Could not find markerDistributionChart canvas element');
            return;
        }

        chartInstances['markerDistributionChart'] = new Chart(markerCtx, {
            type: 'bar',
            data: {
                labels: topMarkers.map(m => m[0]),
                datasets: [{
                    label: 'Cases',
                    data: topMarkers.map(m => m[1]),
                    backgroundColor: '#4a90e2',
                    borderColor: '#357abd',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Top 10 Most Common IHC Markers'
                    },
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Number of Cases'
                        }
                    },
                    x: {
                        ticks: {
                            maxRotation: 0,
                            minRotation: 0
                        }
                    }
                }
            }
        });

        // Add download button after chart is created
        setTimeout(function() {
            addDownloadButton('markerDistributionChart', 'ihc_markers');
        }, 100);
    } catch (error) {
        console.error('Error creating IHC summary chart:', error);
    }
}

function createTimelineChart(timelineData) {
    // Prepare data for chart
    const years = timelineData.map(d => d.year);
    const datasets = [];

    // Get top 5 keywords by total count across all years
    const keywordTotals = {};
    timelineData.forEach(yearData => {
        yearData.keywords.forEach(k => {
            if (!keywordTotals[k.term]) {
                keywordTotals[k.term] = 0;
            }
            keywordTotals[k.term] += k.count;
        });
    });

    // Sort by total count and take top 5
    const top5Keywords = Object.entries(keywordTotals)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(entry => entry[0]);

    // Helper function to capitalize first letter of each word
    function capitalizeWords(str) {
        // Handle special cases like FCoV
        if (str.toLowerCase() === 'fcov') return 'FCoV';
        return str.replace(/\b\w/g, char => char.toUpperCase());
    }

    // Create datasets for each keyword
    top5Keywords.forEach(keyword => {
        const yearCounts = timelineData.map(yearData => {
            const keywordData = yearData.keywords.find(k => k.term === keyword);
            return keywordData ? keywordData.count : 0;
        });

        datasets.push({
            label: capitalizeWords(keyword),
            data: yearCounts,
            fill: false,
            tension: 0,
            pointRadius: 4,
            pointHoverRadius: 6
        });
    });
    
    const ctx = document.getElementById('timelineChart').getContext('2d');
    chartInstances['timelineChart'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: years,
            datasets: datasets
        },
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: 'Most Common Diagnoses (2011-2024)'
                },
                legend: {
                    position: 'bottom'
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Number of Cases'
                    }
                }
            }
        }
    });

    // Add download button after chart is created
    setTimeout(function() {
        addDownloadButton('timelineChart', 'diagnostic_trends');
    }, 100);
}
