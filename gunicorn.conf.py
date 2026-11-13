"""One process is required for the bounded in-memory pending/result registries."""
import os
bind = '0.0.0.0:' + os.environ.get('PORT', '8080')
workers = 1
worker_class = 'sync'
threads = 1
timeout = 30
graceful_timeout = 30
backlog = 64
limit_request_line = 4094
limit_request_fields = 40
limit_request_field_size = 4096
accesslog = None
errorlog = '-'
loglevel = 'warning'
capture_output = False
umask = 0o077
forwarded_allow_ips = ''
secure_scheme_headers = {}
# Do not schedule worker recycling: restarting expires in-process transactions.
max_requests = 0
