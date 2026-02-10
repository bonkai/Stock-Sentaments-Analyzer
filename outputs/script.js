// script.js

let sentimentChart;

document.addEventListener('DOMContentLoaded', function () {
  // Check if data is loaded
  if (typeof sentimentData === 'undefined') {
    console.error('Sentiment data not found!');
    return;
  }

  initializeDashboard();
});

function initializeDashboard() {
  updateLastUpdated();
  initializeSearchFilter();
  initializeCharts();
  updateStatCards();
}

function updateLastUpdated() {
  const lastUpdate = document.getElementById('lastUpdate');
  lastUpdate.textContent = `Last updated: ${sentimentData.lastUpdate}`;
}

// Modified version of your search initialization and filter functions
function initializeSearchFilter() {
  const searchInput = document.getElementById('tickerSearch');
  if (!searchInput) {
      console.error('Search input element not found!');
      return;
  }

  console.log('Search input initialized');
  
  searchInput.addEventListener('input', function(e) {
      const searchTerm = e.target.value.toUpperCase();
      console.log('Search term:', searchTerm);
      filterChart(searchTerm);
  });
}

function filterChart(searchTerm) {
  if (!sentimentChart) {
      console.error('Chart not initialized!');
      return;
  }

  try {
      // Filter tickers that match search term
      const filteredTickers = Object.entries(sentimentData.analysis)
          .filter(([ticker]) => ticker.includes(searchTerm))
          .slice(0, 5); // Limit to top 5 tickers for clarity

      // Update search stats
      const searchStats = document.getElementById('searchStats');
      if (searchStats) {
          searchStats.textContent = `Found ${filteredTickers.length} results`;
      }

      // Clear existing datasets
      sentimentChart.data.datasets = [];

      // Create a dataset for each matching ticker
      filteredTickers.forEach(([ticker, data]) => {
          const color = getSentimentColor(data.stats.average_sentiment, 1);
          
          // Convert mentions to chart data points
          const dataPoints = data.mentions.map(mention => ({
              x: new Date(mention.timestamp * 1000),
              y: mention.sentiment
          }));

          // Sort data points by time
          dataPoints.sort((a, b) => a.x - b.x);

          sentimentChart.data.datasets.push({
              label: ticker,
              data: dataPoints,
              borderColor: color,
              backgroundColor: color.replace('1)', '0.1)'),
              borderWidth: 2,
              tension: 0.4,
              pointRadius: 4,
              pointHoverRadius: 6,
              fill: false
          });
      });

      sentimentChart.update();

  } catch (error) {
      console.error('Error in filterChart:', error);
      console.error('Data structure:', sentimentData.analysis);
  }
}

function initializeCharts() {
  const ctx = document.getElementById('sentimentChart').getContext('2d');
  
  sentimentChart = new Chart(ctx, {
      type: 'line',
      data: {
          datasets: [] // Start empty, will be populated on search
      },
      options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
              intersect: false,
              mode: 'nearest'
          },
          plugins: {
              tooltip: {
                  backgroundColor: 'rgba(255, 255, 255, 0.98)',
                  titleColor: '#1f2937',
                  bodyColor: '#1f2937',
                  titleFont: {
                      weight: 'bold',
                      size: 14
                  },
                  bodyFont: {
                      size: 13
                  },
                  padding: 12,
                  borderColor: 'rgba(229, 231, 235, 0.8)',
                  borderWidth: 1,
                  displayColors: true,
                  callbacks: {
                      label: function(context) {
                          return `Sentiment: ${context.raw.y.toFixed(1)}`;
                      }
                  }
              }
          },
          scales: {
              x: {
                  type: 'time',
                  time: {
                      unit: 'hour',
                      displayFormats: {
                          hour: 'MMM d, h:mm a'
                      }
                  },
                  title: {
                      display: true,
                      text: 'Time'
                  }
              },
              y: {
                  beginAtZero: false,
                  min: 0,
                  max: 100,
                  title: {
                      display: true,
                      text: 'Sentiment Score'
                  },
                  grid: {
                      color: 'rgba(0, 0, 0, 0.05)'
                  }
              }
          }
      }
  });
}

function getSentimentColor(sentiment, alpha = 1) {
  if (sentiment > 61) return `rgba(34, 197, 94, ${alpha})`; // Green
  if (sentiment >= 39 && sentiment <= 61) return `rgba(234, 179, 8, ${alpha})`; // Yellow
  return `rgba(239, 68, 68, ${alpha})`; // Red
}

function prepareChartData() {
  const data = Object.entries(sentimentData.analysis)
    .sort((a, b) => b[1].mention_count - a[1].mention_count)
    .slice(0, 20); // Show top 20 most mentioned tickers

  return {
    labels: data.map(([ticker]) => ticker),
    sentiments: data.map(([_, data]) => data.average_sentiment),
    colors: data.map(([_, data]) => getSentimentColor(data.average_sentiment, 0.6)),
    borderColors: data.map(([_, data]) => getSentimentColor(data.average_sentiment, 1))
  };
}

function getSentimentClass(sentiment) {
  if (sentiment > 61) return 'sentiment-positive';
  if (sentiment >= 39 && sentiment <= 61) return 'sentiment-neutral';
  return 'sentiment-negative';
}

function getSentimentIcon(sentiment) {
  if (sentiment > 61) return '↑';
  if (sentiment >= 39 && sentiment <= 61) return '−';
  return '↓';
}

function updateStatCards() {
  // Update Most Positive Sentiment
  updateStatList('positiveStats', sentimentData.notable.very_positive);

  // Update Most Negative Sentiment
  updateStatList('negativeStats', sentimentData.notable.very_negative);

  // Update Most Discussed
  updateStatList('discussedStats', sentimentData.notable.highly_discussed);

  // Update Trending Up
  updateStatList('trendingStats', sentimentData.notable.trending_up);
}

function updateStatList(elementId, data) {
  const element = document.getElementById(elementId);
  element.innerHTML = data
      .map(([ticker, details]) => {
          const sentimentMatch = details.match(/Sentiment: (\d+\.?\d*)|Latest: (\d+\.?\d*)/);
          const sentiment = sentimentMatch ? 
              parseFloat(sentimentMatch[1] || sentimentMatch[2]) : 
              null;
          
          const sentimentDisplay = sentiment !== null ? `
              <span class="sentiment-number ${getSentimentClass(sentiment)}">
                  ${sentiment.toFixed(1)}
              </span>
          ` : '';

          const formattedDetails = details
              .replace(/Sentiment: \d+\.?\d*|Latest: \d+\.?\d*/, '')
              .trim();

          return `
              <div>
                  <span class="ticker">${ticker}</span>
                  <div class="details">
                      ${formattedDetails ? `<span class="detail-text">${formattedDetails}</span>` : ''}
                      ${sentimentDisplay}
                  </div>
              </div>
          `;
      })
      .join('');
}

function handleError(error) {
  console.error('Dashboard Error:', error);
  alert('An error occurred while loading the dashboard. Please check the console for details.');
}