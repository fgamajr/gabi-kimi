FROM docker.elastic.co/elasticsearch/elasticsearch:8.15.2

# Copy custom configuration
COPY elasticsearch.yml /usr/share/elasticsearch/config/elasticsearch.yml
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod 755 /usr/local/bin/entrypoint.sh

ENV discovery.type=single-node \
    xpack.security.enabled=false \
    ES_JAVA_OPTS="-Xms2g -Xmx2g"

USER root

EXPOSE 9200

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
