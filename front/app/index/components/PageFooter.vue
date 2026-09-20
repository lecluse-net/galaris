<template>
  <footer class="page-footer">
    <div class="footer-line"></div>
    <div class="footer-content">
      <router-link to="/legal" class="footer-link">{{ $t('nav.legal') }}</router-link>
      <span class="separator">|</span>
      <router-link to="/license" class="footer-link">{{ $t('nav.license') }}</router-link>
      <span class="separator">|</span>
      <a
        href="https://lecluse.net"
        class="copyright footer-link"
        target="_blank"
        rel="noopener noreferrer"
      >
        {{ $t('index.footer.copyright') }}
      </a>
    </div>
  </footer>
</template>

<script setup lang="ts">
// Stateless presentation component.
</script>

<style scoped>
.page-footer {
  padding: 8px 16px;
  margin-top: auto;
}

.footer-line {
  height: 1px;
  background: linear-gradient(to right, transparent, #e0e0e0, transparent);
  margin-bottom: 4px;
}

body.body--dark .footer-line {
  background: linear-gradient(to right, transparent, #3a3f47, transparent);
}

.footer-content {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  max-width: 100%;
  font-size: 12px;
  color: gray;
}

.copyright {
  font-weight: 300;
  letter-spacing: 0.3px;
}

.footer-link {
  color: gray;
  text-decoration: none;
  transition: color 0.2s ease;
}

.footer-link:hover {
  color: #414141;
  text-decoration: underline;
}

.separator {
  color: #606060;
  font-size: 10px;
}

body.body--dark .footer-link:hover {
  color: #d0d0d0;
}

body.body--dark .separator {
  color: #8a8a8a;
}

/* Reduce spacing on small screens. */
@media (max-width: 480px) {
  .footer-content {
    gap: 8px;
    font-size: 10px;
  }

  .separator {
    font-size: 9px;
  }
}
</style>
