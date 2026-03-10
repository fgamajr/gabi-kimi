FROM docker.elastic.co/elasticsearch/elasticsearch:8.15.2

USER root

# Copy custom configuration
COPY ops/deploy/es/elasticsearch.yml /usr/share/elasticsearch/config/elasticsearch.yml
COPY ops/deploy/es/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod 755 /usr/local/bin/entrypoint.sh && \
    chown elasticsearch:root /usr/share/elasticsearch/config/elasticsearch.yml

USER elasticsearch

ENV discovery.type=single-node \
    xpack.security.enabled=false \
    ES_JAVA_OPTS="-Xms2g -Xmx2g"

EXPOSE 9200

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
