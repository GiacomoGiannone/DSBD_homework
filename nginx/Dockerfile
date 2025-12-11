FROM nginx:1.29-trixie
RUN apt update &&  \
    apt autoclean && apt -f install

# Copy custom nginx configuration
COPY ./configs/routing.conf /etc/nginx/conf.d/default.conf

# Copy HTML static files
COPY ./html_content/ /usr/share/nginx/html/

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]