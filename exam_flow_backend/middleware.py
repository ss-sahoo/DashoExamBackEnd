"""
Custom middleware for handling PDF responses and CSRF
"""
from django.utils.deprecation import MiddlewareMixin


class DisableCSRFForAPI(MiddlewareMixin):
    """
    Middleware to disable CSRF for API endpoints
    """
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Skip CSRF for API endpoints
        if request.path.startswith('/api/'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None


class PDFResponseMiddleware:
    """
    Middleware to add proper headers for PDF files to allow embedding
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Add headers for PDF files
        if request.path.startswith('/media/') and request.path.endswith('.pdf'):
            response['Content-Type'] = 'application/pdf'
            response['X-Content-Type-Options'] = 'nosniff'
            # Allow embedding in iframes from same origin
            response['X-Frame-Options'] = 'SAMEORIGIN'
            # For cross-origin, use CSP
            response['Content-Security-Policy'] = "frame-ancestors 'self' http://localhost:5173 http://127.0.0.1:5173"
        
        return response
