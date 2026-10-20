// 久留美模拟器 · 四语言运行时（zh / en / ja / ko）
// 依赖 i18n-data.js（window.I18N_DICT）。本文件做两件事：
//   1) t(zh) 查字典；applyI18n(root) 按当前语言扫描 DOM 文本节点做子串翻译
//   2) 顶栏语言切换器：持久化到 localStorage，切换时还原/重翻，并触发 renderAll 刷新动态区
(function () {
  'use strict';
  var D = window.I18N_DICT || {};
  var LANGS = ['zh', 'en', 'ja', 'ko'];

  var L = 'zh';
  try { L = localStorage.getItem('kurumi-lang') || 'zh'; } catch (e) {}
  if (LANGS.indexOf(L) < 0) L = 'zh';
  window.I18N_LANG = L;

  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  // 每种语言预编译一次：长度>=2 的键做最长匹配子串替换；单字键仅在整段相等时替换（防碎裂）
  var cache = {};
  function getRe(lang) {
    if (cache[lang]) return cache[lang];
    var keys = Object.keys(D).filter(function (k) { return k.length >= 2 && D[k][lang]; });
    keys.sort(function (a, b) { return b.length - a.length; });
    var re = keys.length ? new RegExp(keys.map(escapeRe).join('|'), 'g') : null;
    var single = Object.keys(D).filter(function (k) { return k.length < 2 && D[k][lang]; });
    cache[lang] = { re: re, single: single };
    return cache[lang];
  }

  function translateText(txt, lang) {
    var c = getRe(lang);
    if (c.re) txt = txt.replace(c.re, function (m) { return D[m][lang]; });
    for (var i = 0; i < c.single.length; i++) {
      var k = c.single[i];
      if (txt === k) { txt = D[k][lang]; break; }
    }
    return txt;
  }

  // 画布等非 DOM 场景用：把一段中文按当前语言直译（applyI18n 只扫 DOM，管不到 canvas）
  window.i18nText = function (s) { return translateText(String(s), window.I18N_LANG || 'zh'); };

  function skipEl(el) {
    return el.nodeType === 1 && (el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.hasAttribute('data-i18n-skip'));
  }

  function walk(node, lang) {
    if (node.nodeType === 3) {                 // 文本节点
      if (!node.__i18n) node.__i18n = node.nodeValue;   // 首次保存中文原文
      var src = node.__i18n;
      if (src && /[一-鿿]/.test(src)) {
        var nt = translateText(src, lang);
        if (nt !== node.nodeValue) node.nodeValue = nt;
      }
    } else if (node.nodeType === 1) {
      if (skipEl(node)) return;
      var attrs = ['title', 'placeholder', 'aria-label', 'alt', 'label'];
      for (var a = 0; a < attrs.length; a++) {
        var an = attrs[a], v = node.getAttribute(an);
        if (v !== null && /[一-鿿]/.test(v)) {
          if (!node.__i18n_attr) node.__i18n_attr = {};
          if (node.__i18n_attr[an] === undefined) node.__i18n_attr[an] = v;
          var nv = translateText(node.__i18n_attr[an], lang);
          if (nv !== v) node.setAttribute(an, nv);
        }
      }
      var ch = node.childNodes, i;
      for (i = 0; i < ch.length; i++) walk(ch[i], lang);
    }
  }

  function restore(node) {
    if (node.nodeType === 3) {
      if (node.__i18n !== undefined && node.nodeValue !== node.__i18n) node.nodeValue = node.__i18n;
    } else if (node.nodeType === 1) {
      if (skipEl(node)) return;
      if (node.__i18n_attr) {
        var attrs = ['title', 'placeholder', 'aria-label', 'alt', 'label'];
        for (var a = 0; a < attrs.length; a++) {
          var an = attrs[a];
          if (node.__i18n_attr[an] !== undefined && node.getAttribute(an) !== node.__i18n_attr[an])
            node.setAttribute(an, node.__i18n_attr[an]);
        }
      }
      var ch = node.childNodes, i;
      for (i = 0; i < ch.length; i++) restore(ch[i]);
    }
  }

  window.applyI18n = function (root) {
    root = root || document;
    var lang = window.I18N_LANG || 'zh';
    if (lang === 'zh') { restore(root); return; }
    walk(root, lang);
  };

  window.setLang = function (lang) {
    if (LANGS.indexOf(lang) < 0) return;
    window.I18N_LANG = lang;
    try { localStorage.setItem('kurumi-lang', lang); } catch (e) {}
    syncButtons(lang);
    window.applyI18n(document.body);
    if (window.renderAll) window.renderAll();
  };

  function syncButtons(lang) {
    var box = document.getElementById('langSwitch');
    if (!box) return;
    var bs = box.querySelectorAll('button');
    for (var i = 0; i < bs.length; i++)
      bs[i].classList.toggle('on', bs[i].getAttribute('data-lang') === lang);
  }

  function bind() {
    var box = document.getElementById('langSwitch');
    if (!box) return;
    box.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('button[data-lang]');
      if (b) window.setLang(b.getAttribute('data-lang'));
    });
    syncButtons(window.I18N_LANG);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();

  // 初次应用（动态区会由 renderAll 末尾再次扫描）
  if (window.I18N_LANG !== 'zh') window.applyI18n(document.body);
})();
