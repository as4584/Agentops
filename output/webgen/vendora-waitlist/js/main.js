/* Vendora Waitlist — Main JS */
'use strict';

(function () {
  // ── Animated counter ──
  function animateCounter(el, target, duration) {
    var start = 0;
    var startTime = null;
    function step(ts) {
      if (!startTime) startTime = ts;
      var progress = Math.min((ts - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      el.textContent = Math.floor(eased * target).toLocaleString();
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  // Trigger counter animation when visible
  var counted = false;
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting && !counted) {
        counted = true;
        document.querySelectorAll('[data-target]').forEach(function (el) {
          animateCounter(el, parseInt(el.dataset.target, 10), 1800);
        });
      }
    });
  }, { threshold: 0.3 });
  var statsSection = document.querySelector('.stats');
  if (statsSection) observer.observe(statsSection);

  // ── Waitlist form handler ──
  var form = document.getElementById('waitlistForm');
  var success = document.getElementById('waitlistSuccess');
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var email = form.querySelector('input[name="email"]').value;
      if (!email) return;

      // Store locally (will wire to backend later)
      var waitlist = JSON.parse(localStorage.getItem('vendora_waitlist') || '[]');
      if (!waitlist.includes(email)) {
        waitlist.push(email);
        localStorage.setItem('vendora_waitlist', JSON.stringify(waitlist));
      }

      form.style.display = 'none';
      if (success) success.style.display = 'block';
    });
  }

  // ── Smooth scroll for anchor links ──
  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    link.addEventListener('click', function (e) {
      var target = document.querySelector(this.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  // ── Feature card stagger animation on scroll ──
  var cards = document.querySelectorAll('.feature-card');
  var cardObs = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry, i) {
      if (entry.isIntersecting) {
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'translateY(0)';
        cardObs.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });

  cards.forEach(function (card, i) {
    card.style.opacity = '0';
    card.style.transform = 'translateY(24px)';
    card.style.transition = 'opacity 0.5s ease ' + (i * 0.08) + 's, transform 0.5s ease ' + (i * 0.08) + 's';
    cardObs.observe(card);
  });
})();
