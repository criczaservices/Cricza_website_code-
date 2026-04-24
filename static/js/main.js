document.addEventListener('DOMContentLoaded', () => {
    // Mobile navigation toggle (hamburger menu)
    const mobileToggle = document.getElementById('mobile-toggle');
    const navLinks = document.querySelector('.nav-links');
    const navAuth = document.querySelector('.nav-auth');

    if (mobileToggle) {
        mobileToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            mobileToggle.classList.toggle('active');
            navLinks.classList.toggle('active');
            navAuth.classList.toggle('active');
        });

        // Close menu when a nav link is clicked
        document.querySelectorAll('.nav-links a').forEach(link => {
            link.addEventListener('click', () => {
                mobileToggle.classList.remove('active');
                navLinks.classList.remove('active');
                navAuth.classList.remove('active');
            });
        });

        // Close menu when clicking outside the navbar
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.navbar') && navLinks.classList.contains('active')) {
                mobileToggle.classList.remove('active');
                navLinks.classList.remove('active');
                navAuth.classList.remove('active');
            }
        });
    }

    // Skeleton loading simulation for turf cards
    const turfGrid = document.getElementById('turf-grid');
    if (turfGrid) {
        const skeletonCards = document.querySelectorAll('.skeleton-card');
        const actualContent = document.querySelectorAll('.actual-content');

        setTimeout(() => {
            skeletonCards.forEach(card => {
                card.style.transition = 'opacity 0.4s ease';
                card.style.opacity = '0';
                setTimeout(() => { card.style.display = 'none'; }, 400);
            });

            setTimeout(() => {
                actualContent.forEach((card, index) => {
                    card.style.display = 'flex';
                    card.style.opacity = '0';
                    card.style.transform = 'translateY(20px)';
                    setTimeout(() => {
                        card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
                        card.style.opacity = '1';
                        card.style.transform = 'translateY(0)';
                    }, index * 150);
                });
            }, 400);

        }, 1500);
    }

    // Attach close-modal listener if modal exists on this page
    const closeModalBtn = document.querySelector('.close-modal');
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', closeBookingModal);
    }

    // Attach date-change listener if booking-date input exists
    const bookingDate = document.getElementById('booking-date');
    if (bookingDate) {
        bookingDate.addEventListener('change', buildSlots);
    }

    // Close modal on backdrop click
    window.addEventListener('click', (event) => {
        const bookingModal = document.getElementById('booking-modal');
        const descModal = document.getElementById('desc-modal');
        if (bookingModal && event.target === bookingModal) {
            closeBookingModal();
        }
        if (descModal && event.target === descModal) {
            closeDescriptionModal();
        }
    });
    
    // Contact Form Handler
    const contactForm = document.getElementById('contact-form');
    if (contactForm) {
        contactForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const feedback = document.getElementById('contact-feedback');
            const submitBtn = document.getElementById('contact-submit-btn');
            
            const name = document.getElementById('contact-name').value;
            const email = document.getElementById('contact-email').value;
            const subject = document.getElementById('contact-subject').value;
            const message = document.getElementById('contact-message').value;

            // Reset feedback
            feedback.style.display = 'none';
            feedback.className = '';
            
            // Basic UI loading state
            submitBtn.disabled = true;
            submitBtn.textContent = 'Sending...';

            fetch('/api/contact', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, email, subject, message })
            })
            .then(handleResponse)
            .then(data => {
                feedback.style.display = 'block';
                feedback.textContent = data.message;
                
                if (data.success) {
                    feedback.style.backgroundColor = '#f6ffed';
                    feedback.style.color = '#52c41a';
                    feedback.style.border = '1px solid #b7eb8f';
                    contactForm.reset();
                } else {
                    feedback.style.backgroundColor = '#fff2f0';
                    feedback.style.color = '#ff4d4f';
                    feedback.style.border = '1px solid #ffccc7';
                }
            })
            .catch(err => {
                feedback.style.display = 'block';
                feedback.textContent = 'Something went wrong. Please try again later.';
                feedback.style.backgroundColor = '#fff2f0';
                feedback.style.color = '#ff4d4f';
            })
            .finally(() => {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Send Message';
                hideLoader();
            });
        });
    }

    // Auto-bind loader to all standard form submissions (Login, Register, etc.)
    document.querySelectorAll('form').forEach(form => {
        // Skip hidden forms or forms handled by custom logic
        const action = form.getAttribute('action');
        if (form.id === 'contact-form' || 
            form.id === 'delete-keys-form' ||
            (action && action.includes('coupon')) ||
            (action && action.includes('remove'))) return;
        
        form.addEventListener('submit', () => {
            showLoader('Processing...');
        });
    });

    // Navigation loader for "shifting on the tab"
    document.querySelectorAll('.nav-links a, .nav-auth a, .brand-logo').forEach(link => {
        link.addEventListener('click', (e) => {
            const href = link.getAttribute('href');
            // Only show loader if it's an internal link and not an anchor
            if (href && !href.startsWith('#') && !href.includes('logout') && !href.includes('javascript:')) {
                showLoader('Loading...');
            }
        });
    });
});

/*=====================================
  LOADER CONTROLS
=====================================*/
function showLoader(text = 'Cricza') {
    const loader = document.getElementById('cricza-loader');
    const loaderText = loader ? loader.querySelector('.loader-text') : null;
    if (loader) {
        if (loaderText) loaderText.textContent = text;
        loader.classList.add('show');
    }
}

function hideLoader() {
    const loader = document.getElementById('cricza-loader');
    if (loader) {
        loader.classList.remove('show');
    }
}

// Handler for Google Auth
function handleGoogleAuth(action) {
    window.location.href = '/login/google';
}

// Homepage turf search filter (by name or pincode)
function filterTurfs() {
    const input = document.getElementById("turfSearch");
    if (!input) return;
    const filter = input.value.toLowerCase().trim();
    const cards = document.querySelectorAll('.turf-card.actual-content');
    cards.forEach(card => {
        const name = card.getAttribute('data-turf-name') || '';
        const pincode = card.getAttribute('data-turf-pincode') || '';
        card.style.display = (name.includes(filter) || pincode.includes(filter)) ? 'flex' : 'none';
    });
}

// =============================================
//   BOOKING MODAL STATE
// =============================================

let currentTurfId = null;
let currentTurfName = null;
let currentBaseCost = 0;
let currentOpenTime = 0;
let currentCloseTime = 0;
let selectedSlots = [];
let appliedCoupon = null;
let appliedDiscount = 0;

// =============================================
//   BOOKING MODAL FUNCTIONS
// =============================================

function openBookingModal(turfId, turfName, baseCost, openTime, closeTime) {
    // Lazy DOM lookup — works whether modal is on index or dashboard
    const bookingModal = document.getElementById('booking-modal');
    const modalTurfName = document.getElementById('modal-turf-name');
    const timeSlotsContainer = document.getElementById('time-slots-container');
    const bookingDate = document.getElementById('booking-date');
    const footer = document.getElementById('modal-footer');

    if (!bookingModal || !modalTurfName || !timeSlotsContainer || !bookingDate) {
        console.error('Booking modal elements not found on this page.');
        return;
    }

    currentTurfId = turfId;
    currentTurfName = turfName;
    currentBaseCost = parseFloat(baseCost);
    currentOpenTime = parseInt(openTime);
    currentCloseTime = parseInt(closeTime);
    selectedSlots = [];
    appliedCoupon = null;
    appliedDiscount = 0;

    modalTurfName.textContent = turfName;
    timeSlotsContainer.innerHTML = '';
    
    // Reset coupon UI
    const couponInput = document.getElementById('coupon-code-input');
    const couponFeedback = document.getElementById('coupon-feedback');
    if (couponInput) couponInput.value = '';
    if (couponFeedback) {
        couponFeedback.textContent = '';
        couponFeedback.style.color = 'inherit';
    }

    if (footer) footer.style.display = 'none';

    // Set date picker range: today → today+2
    const today = new Date();
    const tzOffset = today.getTimezoneOffset() * 60000;
    const localToday = new Date(today.getTime() - tzOffset);
    const minDateStr = localToday.toISOString().split('T')[0];
    const maxDate = new Date(localToday);
    maxDate.setDate(maxDate.getDate() + 2);

    bookingDate.min = minDateStr;
    bookingDate.max = maxDate.toISOString().split('T')[0];
    bookingDate.value = minDateStr;

    // Handle offline customer section visibility
    const offlineSection = document.getElementById('offline-customer-section');
    const isOwnerDashboard = window.location.pathname.includes('/dashboard/owner');
    if (offlineSection) {
        offlineSection.style.display = isOwnerDashboard ? 'block' : 'none';
        // Reset fields
        const offName = document.getElementById('offline-name');
        const offEmail = document.getElementById('offline-email');
        const offPhone = document.getElementById('offline-phone');
        if (offName) offName.value = '';
        if (offEmail) offEmail.value = '';
        if (offPhone) offPhone.value = '';
    }

    // Show modal
    bookingModal.style.display = 'flex';
    setTimeout(() => { bookingModal.classList.add('show'); }, 10);

    buildSlots();
}

function buildSlots() {
    const bookingDate = document.getElementById('booking-date');
    const container = document.getElementById('time-slots-container');
    const footer = document.getElementById('modal-footer');

    if (!bookingDate || !container) return;
    const selectedDate = bookingDate.value;
    if (!selectedDate) return;

    if (currentOpenTime >= currentCloseTime) {
        container.innerHTML = '<p style="text-align:center; padding:2rem; color:var(--text-secondary);">No valid slots available. Contact turf owner.</p>';
        return;
    }

    fetch(`/api/turf/${currentTurfId}/booked_slots?date=${selectedDate}`)
        .then(handleResponse)
        .then(data => {
            const bookedSlots = data.booked_slots || [];
            const isOffDate = data.is_off_date || false;

            container.innerHTML = '';
            selectedSlots = [];
            updateTotalPrice();

            if (isOffDate) {
                if (footer) footer.style.display = 'none';
                container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2.5rem; background: #fff1f0; border: 1px solid #ffa39e; border-radius: 12px; color: #cf222e; font-weight: 600;">⚠️ This turf is closed on the selected date. Please pick another date.</div>';
                return;
            }

            if (footer) footer.style.display = 'block';

            const categories = [
                { name: 'Morning', icon: '☀️', start: 0, end: 12, slots: [] },
                { name: 'Afternoon', icon: '🌤️', start: 12, end: 16, slots: [] },
                { name: 'Evening', icon: '🌇', start: 16, end: 19, slots: [] },
                { name: 'Night', icon: '🌙', start: 19, end: 24, slots: [] }
            ];

            for (let hour = currentOpenTime; hour < currentCloseTime; hour++) {
                const timeString = `${hour}:00 - ${hour + 1}:00`;
                const isBooked = bookedSlots.includes(timeString);
                const cat = categories.find(c => hour >= c.start && hour < c.end);
                if (cat) cat.slots.push({ timeString, isBooked });
            }

            categories.forEach(cat => {
                if (cat.slots.length === 0) return;

                const catDiv = document.createElement('div');
                catDiv.className = 'slot-category';
                catDiv.innerHTML = `
                    <div class="category-header">
                        <span class="category-icon">${cat.icon}</span>
                        <h4>${cat.name}</h4>
                    </div>
                    <div class="slots-grid"></div>
                `;
                const grid = catDiv.querySelector('.slots-grid');

                cat.slots.forEach(slot => {
                    const slotCard = document.createElement('div');
                    slotCard.className = 'time-slot-pill' + (slot.isBooked ? ' booked' : '');
                    
                    if (slot.isBooked) {
                        slotCard.innerHTML = `
                            <div class="slot-time" style="text-decoration: line-through;">${slot.timeString}</div>
                            <div class="booked-label">Booked</div>
                        `;
                    } else {
                        slotCard.setAttribute('data-slot', slot.timeString);
                        slotCard.addEventListener('click', function() { toggleSlot(slot.timeString, this); });
                        slotCard.innerHTML = `
                            <div class="slot-time">${slot.timeString}</div>
                            <div class="slot-price">₹${currentBaseCost}</div>
                        `;
                    }
                    grid.appendChild(slotCard);
                });
                container.appendChild(catDiv);
            });
        })
        .catch(err => console.error('Error fetching slots:', err));
}

function toggleSlot(timeString, element) {
    const index = selectedSlots.indexOf(timeString);
    if (index > -1) {
        selectedSlots.splice(index, 1);
        element.classList.remove('selected');
    } else {
        selectedSlots.push(timeString);
        element.classList.add('selected');
    }
    updateTotalPrice();
}

function updateTotalPrice() {
    const totalPriceEl = document.getElementById('booking-total-price');
    const countEl = document.getElementById('selected-slots-count');
    
    if (totalPriceEl) {
        let total = selectedSlots.length * currentBaseCost;
        if (appliedDiscount > 0) {
            total = Math.max(0, total - appliedDiscount);
        }
        totalPriceEl.innerText = total;
    }
    
    if (countEl) {
        countEl.innerText = `${selectedSlots.length} slot${selectedSlots.length !== 1 ? 's' : ''} selected`;
    }
}

function applyCoupon() {
    const codeInput = document.getElementById('coupon-code-input');
    const feedback = document.getElementById('coupon-feedback');
    const code = codeInput.value.trim().toUpperCase();

    if (!code) {
        feedback.textContent = 'Please enter a coupon code.';
        feedback.style.color = 'red';
        return;
    }

    if (selectedSlots.length === 0) {
        feedback.textContent = 'Select at least one slot before applying coupon.';
        feedback.style.color = 'orange';
        return;
    }

    fetch('/api/validate_coupon', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ turf_id: currentTurfId, code: code })
    })
    .then(handleResponse)
    .then(data => {
        if (data.success) {
            appliedCoupon = code;
            appliedDiscount = data.discount;
            feedback.textContent = data.message;
            feedback.style.color = 'green';
            updateTotalPrice();
        } else {
            appliedCoupon = null;
            appliedDiscount = 0;
            feedback.textContent = data.message;
            feedback.style.color = 'red';
            updateTotalPrice();
        }
    })
    .catch(err => {
        console.error('Coupon error:', err);
        feedback.textContent = 'Error validating coupon.';
        feedback.style.color = 'red';
    });
}

function closeBookingModal() {
    const bookingModal = document.getElementById('booking-modal');
    if (bookingModal) {
        bookingModal.classList.remove('show');
        setTimeout(() => { bookingModal.style.display = 'none'; }, 300);
    }
}

// =============================================
//   DESCRIPTION MODAL FUNCTIONS
// =============================================

function showFullDescription(turfName, description) {
    const modal = document.getElementById('desc-modal');
    const title = document.getElementById('desc-modal-title');
    const body = document.getElementById('desc-modal-body');

    if (!modal || !title || !body) return;

    title.textContent = turfName;
    body.textContent = description;

    modal.style.display = 'flex';
    setTimeout(() => { modal.classList.add('show'); }, 10);
}

function closeDescriptionModal() {
    const modal = document.getElementById('desc-modal');
    if (modal) {
        modal.classList.remove('show');
        setTimeout(() => { modal.style.display = 'none'; }, 300);
    }
}

function processMultiBooking() {
    if (selectedSlots.length === 0) {
        alert('Please select at least one time slot.');
        return;
    }

    const bookingDate = document.getElementById('booking-date');
    if (!bookingDate) return;

    const date = bookingDate.value;
    const totalCost = parseFloat(document.getElementById('booking-total-price').innerText);
    const timeSlotsString = selectedSlots.join(', ');
    const isOwnerDashboard = window.location.pathname.includes('/dashboard/owner');

    // 1. Handle Manual Booking (Owner Dashboard)
    if (isOwnerDashboard) {
        showLoader('Processing...');
        fetch('/api/book_manual', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                turf_id: currentTurfId,
                time_slot: timeSlotsString,
                cost: totalCost,
                date: date,
                offline_name: document.getElementById('offline-name') ? document.getElementById('offline-name').value : null,
                offline_email: document.getElementById('offline-email') ? document.getElementById('offline-email').value : null,
                offline_phone: document.getElementById('offline-phone') ? document.getElementById('offline-phone').value : null,
                coupon_code: appliedCoupon
            })
        })
        .then(handleResponse)
        .then(data => {
            hideLoader();
            if (data.success) {
                alert(data.message);
                window.location.reload();
            } else {
                alert(data.message);
            }
        })
        .catch(err => {
            hideLoader();
            console.error(err);
        });
        return;
    }

    // 2. Handle Online Booking (Customer Flow)
    // First, Create Razorpay Order
    showLoader('Preparing Payment...');
    fetch('/api/payment/create-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            turf_id: currentTurfId,
            time_slot: timeSlotsString,
            cost: totalCost,
            date: date,
            coupon_code: appliedCoupon
        })
    })
    .then(handleResponse)
    .then(data => {
        hideLoader();
        if (!data.success) {
            alert(data.message || 'Error creating order');
            return;
        }

        const options = {
            "key": data.key_id,
            "amount": data.amount,
            "currency": "INR",
            "name": "Cricza",
            "description": `Booking for ${currentTurfName}`,
            "order_id": data.order_id,
            "handler": function (response) {
                // Verify Payment
                showLoader('Verifying Payment...');
                fetch('/api/payment/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        razorpay_payment_id: response.razorpay_payment_id,
                        razorpay_order_id: response.razorpay_order_id,
                        razorpay_signature: response.razorpay_signature,
                        booking_id: data.booking_id
                    })
                })
                .then(handleResponse)
                .then(verification => {
                    hideLoader();
                    if (verification.success) {
                        alert(verification.message);
                        window.location.href = '/booking';
                    } else {
                        alert(verification.message || 'Verification failed');
                    }
                })
                .catch(err => hideLoader());
            },
            "prefill": {
                "name": "", // We could pass current user name here
                "email": ""
            },
            "theme": {
                "color": "#e0f465"
            },
            "modal": {
                "ondismiss": function() {
                    // Release the slot immediately if user closes the window
                    fetch(`/api/booking/${data.booking_id}/cancel`, { method: 'POST' });
                    console.log('Payment window closed. Slot released.');
                }
            }
        };
        const rzp1 = new Razorpay(options);
        rzp1.open();
    })
    .catch(error => {
        hideLoader();
        console.error('Booking error:', error);
        alert('You must be logged in to book a slot.');
        window.location.href = '/login';
    });
}

function startSubscription(plan, price) {
    showLoader('Initializing...');
    fetch('/api/subscription/create-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: plan, price: price })
    })
    .then(handleResponse)
    .then(data => {
        hideLoader();
        if (!data.success) {
            alert(data.message || 'Error creating subscription');
            return;
        }

        const options = {
            "key": data.key_id,
            "amount": data.amount,
            "currency": "INR",
            "name": "Cricza Partner",
            "description": `Subscription for ${plan}`,
            "order_id": data.order_id,
            "handler": function (response) {
                showLoader('Upgrading Account...');
                fetch('/api/subscription/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        razorpay_payment_id: response.razorpay_payment_id,
                        razorpay_order_id: response.razorpay_order_id,
                        razorpay_signature: response.razorpay_signature,
                        plan: plan,
                        price: price
                    })
                })
                .then(handleResponse)
                .then(verification => {
                    hideLoader();
                    if (verification.success) {
                        alert('Payment Successful! Your subscription is now active.');
                        window.location.href = '/dashboard/owner';
                    } else {
                        alert(verification.message || 'Verification failed');
                    }
                })
                .catch(err => hideLoader());
            },
            "theme": { "color": "#e0f465" }
        };
        const rzp1 = new Razorpay(options);
        rzp1.open();
    })
    .catch(err => hideLoader());
}

/*=====================================
  Workflow Reveal Logic
=====================================*/
document.addEventListener('DOMContentLoaded', () => {
    const revealSteps = document.querySelectorAll('.reveal-step');
    
    const observerOptions = {
        threshold: 0.2,
        rootMargin: '0px 0px -50px 0px'
    };

    const stepObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);

    revealSteps.forEach(step => {
        stepObserver.observe(step);
    });
});

/*=====================================
  TOAST NOTIFICATION SYSTEM
=====================================*/
function showToast(message, type = 'error', title = 'Notice') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast ' + type + ' show';
    let icon = type === 'error' ? '??' : (type === 'success' ? '?' : '??');
    toast.innerHTML = '<div class=\"toast-icon\">' + icon + '</div><div class=\"toast-content\"><div class=\"toast-title\">' + title + '</div><div class=\"toast-message\">' + message + '</div></div>';
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400);
    }, 5000);
}

function handleResponse(res) {
    if (res.status === 429) {
        res.json().then(data => showToast(data.message || 'Too many requests.', 'error', 'Slow Down'));
        throw new Error('Rate limit');
    }
    return res.json();
}
