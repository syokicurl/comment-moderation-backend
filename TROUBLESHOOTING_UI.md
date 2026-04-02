# 🛠️ Modern Frontend - Troubleshooting Guide

## Common Issues & Solutions

### 🔴 Issue: Modal doesn't appear when I click "Sign In"

**Symptom**: Click "Sign In" button, nothing happens

**Possible Causes**:
1. AuthModal state not updating
2. Modal rendering issue
3. Event handler not attached

**Solutions**:

**Step 1**: Check console for errors
```javascript
// Open browser DevTools (F12)
// Go to Console tab
// Look for any red error messages
```

**Step 2**: Verify AuthModal state
```typescript
// In app/page.tsx, check:
const [authModal, setAuthModal] = useState({ isOpen: false, type: "login" })

// Should be passed to AuthModal:
<AuthModal isOpen={authModal.isOpen} onClose={handleCloseAuth} />
```

**Step 3**: Check button onClick handler
```typescript
const handleOpenAuth = (type: "login" | "register") => {
  setAuthModal({ isOpen: true, type })
}

// Button should have:
onClick={() => handleOpenAuth("login")}
```

**Resolution**: If still not working, ensure:
- ✅ AuthModal component is imported
- ✅ State is initialized
- ✅ Click handlers are connected
- ✅ Modal has `isOpen={true}`

---

### 🔴 Issue: 3D hero effect doesn't track mouse

**Symptom**: Hero section doesn't tilt when moving mouse

**Possible Causes**:
1. Mouse tracking not initialized
2. CSS perspective not applied
3. Browser doesn't support CSS 3D

**Solutions**:

**Step 1**: Check browser compatibility
```javascript
// Try on Chrome or Firefox
// Safari may have different behavior
// Try on different device
```

**Step 2**: Verify CSS is loaded
```bash
# Open browser DevTools (F12)
# Go to Elements tab
# Find hero container
# Check computed styles for:
#   transform-style: preserve-3d
#   perspective: 1200px
```

**Step 3**: Test mouse tracking
```javascript
// In browser console:
// Move mouse over hero section
const hero = document.querySelector('[style*="--rotateX"]')
console.log(hero?.style.getPropertyValue('--rotateX'))
// Should show changing values like: "5deg", "-10deg", etc
```

**Resolution**: If not working:
- ✅ Check browser (Chrome/Firefox recommended)
- ✅ Verify CSS is not overridden
- ✅ Make sure mouse is directly over hero container
- ✅ Use oldest supported browser for testing

---

### 🔴 Issue: Back button doesn't appear

**Symptom**: Back arrow button never shows in navigation

**Possible Causes**:
1. NavigationProvider not wrapping app
2. Navigation history not tracking
3. canGoBack() always returns false

**Solutions**:

**Step 1**: Verify NavigationProvider wrapping
```typescript
// In app/page.tsx (or root layout if you move it there):
<NavigationProvider>
  {/* All content should be inside */}
</NavigationProvider>
```

**Step 2**: Check navigation history
```javascript
// In browser console:
// After navigating to multiple pages
// The back button should appear
```

**Step 3**: Test canGoBack()
```javascript
// If you added debugging:
console.log(canGoBack())  // Should be true after navigation
```

**Resolution**:
- ✅ Ensure NavigationProvider wraps entire app
- ✅ Navigate between at least 2 pages (history needs depth)
- ✅ Back button only shows when there is history to return to
- ✅ Refresh page resets history (expected behavior)

---

### 🔴 Issue: Modal animates too fast or too slow

**Symptom**: Modal pops in too quickly or slowly

**Possible Causes**:
1. Animation duration too short/long
2. CSS not applied correctly
3. System performance affecting timing

**Solutions**:

**Step 1**: Locate animation definition
```bash
# File: components/ui/navigation-modal.tsx
# Find: slideInFromBottom animation
# Look for: animation: ... Xms ...
```

**Step 2**: Adjust timing
```css
/* Current (in globals.css): */
@keyframes slideInFromBottom {
  /* Duration: 0.3s = 300ms */
}

/* To make faster, change CSS to: */
@keyframes slideInFromBottom {
  animation: slideInFromBottom 0.15s ease-out;  /* 2x faster */
}

/* To make slower: */
@keyframes slideInFromBottom {
  animation: slideInFromBottom 0.6s ease-out;   /* 2x slower */
}
```

**Step 3**: Test timing
- Open modal
- Observe animation speed
- Adjust and refresh page
- Repeat until happy

**Resolution**:
- ✅ Edit animation durations in `globals.css`
- ✅ Use browser DevTools to measure timing
- ✅ Get feedback from users on preferred speed
- ✅ Generally 200-400ms feels smooth

---

### 🔴 Issue: Animations not smooth (choppy/laggy)

**Symptom**: Animations stutter or have low frame rate

**Possible Causes**:
1. JavaScript blocking rendering
2. Too many animations running
3. Browser performance issue
4. Other code interfering

**Solutions**:

**Step 1**: Check browser performance
```javascript
// Open DevTools → Performance tab
// Record animation
// Look for 60fps target (should be green)
// If red/orange, there's a performance issue
```

**Step 2**: Check for interfering code
```javascript
// Console (F12):
// Close all extensions
// Try in Incognito/Private mode
// Try different browser
```

**Step 3**: Reduce animation complexity
```css
/* If too many animations running: */
/* Reduce number of floating elements */
/* Reduce blur intensity (backdrop-blur-md instead of -xl) */
/* Reduce animation duration */
```

**Resolution**:
- ✅ Test on different browser/device
- ✅ Check for CPU/GPU constraints
- ✅ Reduce animation complexity if needed
- ✅ Close other applications
- ✅ Clear browser cache (Ctrl+Shift+Delete)

---

### 🔴 Issue: Modal appears behind other content

**Symptom**: Modal is visible but blocked by other elements

**Possible Causes**:
1. Z-index not high enough
2. Parent container has overflow hidden
3. Stacking context issue

**Solutions**:

**Step 1**: Check z-index values
```typescript
// In navigation-modal.tsx:
// Background: z-40
// Modal: z-50
// Make sure no other elements have higher z-index
```

**Step 2**: Examine computed z-index
```javascript
// DevTools → Elements tab
// Select modal element
// Check computed styles
// Find any elements with z-index > 50
```

**Step 3**: Increase z-index if needed
```typescript
// In navigation-modal.tsx:
// Change z-40 to z-30 (could help in some cases)
// OR change z-50 to z-[9999] if needed
```

**Resolution**:
- ✅ Check z-index hierarchy
- ✅ Ensure no elements have z-index > modal
- ✅ Move NavigationModal to top of component tree
- ✅ Use relative/absolute positioning correctly

---

### 🟡 Issue: Page looks different on mobile

**Symptom**: Layout broken or elements misaligned on phone

**Possible Causes**:
1. Responsive design not working
2. Viewport meta tag missing
3. Tailwind breakpoints not triggered
4. CSS overrides on mobile

**Solutions**:

**Step 1**: Check viewport meta tag
```html
<!-- In app/layout.tsx or next.js config, should have: -->
<meta name="viewport" content="width=device-width, initial-scale=1" />
```

**Step 2**: Test responsive breakpoints
```bash
# Open Chrome DevTools
# Press Ctrl+Shift+M for device emulation
# Test different screen sizes (mobile, tablet, desktop)
```

**Step 3**: Check Tailwind breakpoints
```typescript
// Responsive classes:
// hidden md:flex     → Hidden on mobile, visible on tablet+
// px-4 md:px-6      → Different padding on different sizes
// flex-col lg:flex-row → Stack on mobile, row on desktop
```

**Resolution**:
- ✅ Test on actual mobile device
- ✅ Use Chrome DevTools device emulation
- ✅ Check Tailwind responsive classes
- ✅ Ensure viewport meta tag is set
- ✅ Test portrait and landscape orientations

---

### 🟡 Issue: Colors don't match my brand

**Symptom**: Primary color is wrong shade

**Possible Causes**:
1. CSS variable not updated
2. Color cache from old build
3. Dark mode applied
4. Multiple color definitions

**Solutions**:

**Step 1**: Find color definition
```css
/* File: app/globals.css */
/* Line 4-5: */
--primary: oklch(0.51 0.18 255);  /* This is the main color */
```

**Step 2**: Update to your color
```css
/* Option 1: Use your HTML color code */
--primary: #5B21B6;  /* Example purple */

/* Option 2: Use oklch (modern, better) */
--primary: oklch(0.55 0.20 280);  /* Custom color */

/* To find oklch values: use https://oklch.com/ */
```

**Step 3**: Clear cache and refresh
```bash
# Hard refresh: Ctrl+Shift+R (or Cmd+Shift+R on Mac)
# Or: npm run build && npm start
```

**Resolution**:
- ✅ Edit color in `app/globals.css`
- ✅ Hard refresh page (Ctrl+Shift+R)
- ✅ Check dark mode setting
- ✅ Use https://oklch.com/ to find color values
- ✅ Test on multiple browsers

---

### 🟡 Issue: Back button not working properly

**Symptom**: Back button appears but clicking does nothing or goes to wrong page

**Possible Causes**:
1. Navigation history not tracking
2. Router not working
3. Wrong navigation logic
4. History state corrupted

**Solutions**:

**Step 1**: Test navigation manually
```javascript
// In browser console:
console.log(window.history.length)  // Should increase with each click
```

**Step 2**: Debug goBack function
```typescript
// In lib/navigation-context.tsx:
const goBack = useCallback(() => {
  console.log('Going back...')  // Add logging
  if (navigationStack.length > 1) {
    // Clear previous implementation
  }
  router.back()  // Fallback to browser back
}, [navigationStack, router])
```

**Step 3**: Test with browser back button
```javascript
// Does browser's back button work?
// If yes, issue is with custom implementation
// If no, issue is deeper (not navigation-related)
```

**Resolution**:
- ✅ Verify history is tracking (check console)
- ✅ Use browser back button as fallback
- ✅ Test different navigation scenarios
- ✅ Check if issue is page-specific
- ✅ Consider using `window.history.back()` instead

---

### 🟡 Issue: TypeScript errors

**Symptom**: Red squiggly lines or build errors

**Possible Causes**:
1. Type definitions missing
2. Component prop types mismatch
3. TypeScript config issue
4. Dependencies not installed

**Solutions**:

**Step 1**: Check error message
```bash
# Build the project to see errors:
npm run build
# Read the error message carefully
```

**Step 2**: Install missing types (if needed)
```bash
# Most common:
npm install --save-dev @types/node @types/react
```

**Step 3**: Fix type issues
```typescript
// Example error: "Property 'isOpen' does not exist on type 'Props'"
// Solution: Add type to interface:
interface AuthModalProps {
  isOpen: boolean    // ← Add this
  onClose: () => void
}
```

**Resolution**:
- ✅ Read error message carefully
- ✅ Check component prop types
- ✅ Install missing dependencies
- ✅ Run `npm i` to ensure all deps installed
- ✅ Restart dev server after changes

---

## 🎯 Performance Debugging

### Check Frame Rate
```javascript
// In browser console:
// 1. Open DevTools → Performance tab
// 2. Click record
// 3. Trigger animation (move mouse over hero)
// 4. Stop recording
// 5. Look for green bars (60fps) vs red (< 60fps)

// If seeing red bars:
// - Reduce animation complexity
// - Check for heavy JavaScript
// - Close other browser tabs
```

### Monitor Memory Usage
```javascript
// In DevTools → Memory tab:
// 1. Take heap snapshot
// 2. Interact with app
// 3. Take another snapshot
// 4. Compare sizes

// If memory growing:
// - Check for memory leaks
// - Remove event listeners on unmount
// - Clear intervals/timeouts
```

---

## 📋 Debugging Checklist

When something goes wrong:

- [ ] Check browser console for errors (F12)
- [ ] Check browser console for warnings
- [ ] Hard refresh page (Ctrl+Shift+R)
- [ ] Clear browser cache
- [ ] Try different browser
- [ ] Check responsive design (F12 mobile mode)
- [ ] Look for typos in code
- [ ] Verify imports are correct
- [ ] Check that files exist
- [ ] Run `npm install` again
- [ ] Restart dev server
- [ ] Check git status for uncommitted changes
- [ ] Verify dependencies installed

---

## 🆘 Still Not Working?

### Last Resort Fixes

**Option 1: Clear Everything**
```bash
# Delete node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
npm run dev
```

**Option 2: Check File Modifications**
```bash
# See what files changed
git status

# Reset to known good state
git checkout components/landing/modern-nav.tsx
```

**Option 3: Start from Backup**
```bash
# If you have app.py.backup, there might be other backups
# Check for: *.backup or filename-bak.*
ls -la *.backup  # Linux/Mac
dir *.backup     # Windows
```

**Option 4: Compare with Original**
```bash
# If something broke, compare versions
git diff components/landing/modern-nav.tsx
git show HEAD:components/landing/modern-nav.tsx
```

---

## 📞 Need More Help?

### Check Documentation
- [QUICK_START_UI.md](QUICK_START_UI.md) - Quick reference
- [MODERN_UI_GUIDE.md](MODERN_UI_GUIDE.md) - Full documentation
- [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md) - Technical details

### Verify Installation
```bash
# Check npm packages:
npm list three            # Should show in project (even if not used)
npm list react            # Should show installed
npm list next             # Should show installed

# Check Next.js version:
npx next --version        # Should be 16+
```

### Test Basic Functionality
```bash
# Start dev server
npm run dev

# Go to http://localhost:3000
# Check browser console (F12)
# Test each feature one by one

# If error, note exact error message
# Google the error message
# Check project issues/FAQ
```

---

## 🎉 Success Indicators

When everything is working:

✅ Dev server starts without errors  
✅ Landing page loads at http://localhost:3000  
✅ Navigation bar shows with gradient logo  
✅ 3D hero responds to mouse movement  
✅ Modals pop in and out smoothly  
✅ Back button appears after navigation  
✅ All animations run at 60fps  
✅ No console errors or warnings  
✅ Mobile responsive layout works  
✅ All links navigate correctly  

---

**Last Updated**: April 2, 2026  
**Need Help?** Check the main documentation files above!

