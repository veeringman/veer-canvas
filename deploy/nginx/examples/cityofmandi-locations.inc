# Shared locations for City of Mandi vhosts.
# CMS is /cms (VeerCanvas). /admin is the hub operator desk (static).

location ^~ /.well-known/acme-challenge/ {
    default_type text/plain;
}

location = /cms { return 301 /cms/; }
location ^~ /cms/ {
    proxy_pass http://127.0.0.1:8085/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /cms;
    proxy_connect_timeout 60s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;
}

location = /admin { return 301 /admin/; }
location ^~ /admin/ {
    try_files $uri $uri/ /admin/index.html;
}

location ^~ /static/ {
    proxy_pass http://127.0.0.1:8085/static/;
    proxy_set_header Host $host;
}

location ^~ /site/ {
    proxy_pass http://127.0.0.1:8085/site/;
    proxy_set_header Host $host;
}

location = /login {
    return 302 /admin/;
}

location = /logout {
    return 302 /admin/;
}

location ^~ /api/ {
    proxy_pass http://127.0.0.1:8085/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location ^~ /b/ {
    try_files /business.html =404;
}

location = /join { try_files /join.html =404; }
location = /publish { try_files /publish.html =404; }
location = /adda { try_files /adda.html =404; }

location / {
    try_files $uri $uri/ =404;
}

location = /projects.json { return 404; }

location = /catalog-exclusions.json {
    add_header Cache-Control "no-store, no-cache, must-revalidate";
    try_files $uri =404;
}

location = /projects-public.json {
    add_header Cache-Control "no-store, no-cache, must-revalidate";
    try_files $uri =404;
}

location = /site-meta.json {
    add_header Cache-Control "no-store, no-cache, must-revalidate";
    try_files $uri =404;
}

location = /hub.json {
    add_header Cache-Control "no-store, no-cache, must-revalidate";
    try_files $uri =404;
}

location = /businesses.json {
    add_header Cache-Control "no-store, no-cache, must-revalidate";
    try_files $uri =404;
}

location ~* \.(?:css|js)$ {
    add_header Cache-Control "no-cache, must-revalidate";
    etag on;
    access_log off;
}

location ~* \.(?:jpg|jpeg|gif|png|svg|ico|webp|ttf|woff|woff2)$ {
    expires 30d;
    access_log off;
}
