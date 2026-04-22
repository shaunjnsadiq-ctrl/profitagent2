(function() {
  'use strict';

  var PA = {
    version: '1.0.0',
    storeId: null,
    endpoint: 'https://profitagent2-production.up.railway.app/pixel/event',
    sessionId: null,
    queue: []
  };

  // Get store ID from script tag
  var scripts = document.querySelectorAll('script[data-store]');
  for (var i = 0; i < scripts.length; i++) {
    if (scripts[i].src && scripts[i].src.indexOf('pa.js') > -1) {
      PA.storeId = scripts[i].getAttribute('data-store');
      break;
    }
  }

  // Generate session ID
  PA.sessionId = 'sess_' + Math.random().toString(36).substr(2, 12) + '_' + Date.now();

  // Core track function
  PA.track = function(eventName, properties) {
    var payload = {
      store_id: PA.storeId,
      session_id: PA.sessionId,
      event: eventName,
      properties: properties || {},
      url: window.location.href,
      referrer: document.referrer || '',
      timestamp: new Date().toISOString(),
      pixel_version: PA.version
    };

    // Use sendBeacon if available (non-blocking)
    if (navigator.sendBeacon) {
      var blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
      navigator.sendBeacon(PA.endpoint, blob);
    } else {
      // Fallback to fetch
      fetch(PA.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true
      }).catch(function() {});
    }

    // Log in demo mode
    if (window.PA_DEBUG) {
      console.log('[ProfitAgent Pixel] Event fired:', eventName, payload);
    }
  };

  // Auto-track page view
  PA.track('page_view', {
    title: document.title,
    path: window.location.pathname
  });

  // Auto-track clicks on add-to-cart buttons
  document.addEventListener('click', function(e) {
    var el = e.target;
    var text = (el.textContent || '').toLowerCase();
    var cls = (el.className || '').toLowerCase();
    if (
      text.indexOf('add to cart') > -1 ||
      text.indexOf('add to bag') > -1 ||
      cls.indexOf('add-to-cart') > -1 ||
      cls.indexOf('addtocart') > -1 ||
      el.getAttribute('name') === 'add'
    ) {
      PA.track('add_to_cart', {
        button_text: el.textContent.trim().substring(0, 50)
      });
    }
  });

  // Expose globally for Shopify liquid integration
  window.ProfitAgentPixel = PA;
  window.pa = function(event, props) { PA.track(event, props); };

  // Signal pixel loaded
  PA.track('pixel_loaded', {
    store_id: PA.storeId,
    demo_mode: !PA.storeId || PA.storeId === 'YOUR-STORE-ID'
  });

})();
