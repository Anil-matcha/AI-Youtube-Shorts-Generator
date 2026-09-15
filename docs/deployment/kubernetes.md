# Kubernetes deployment target

Helm packaging is supported for a documented, CPU-only Kubernetes target:
Kubernetes 1.28 or newer, one `Deployment`, a `ReadWriteOnce` PVC mounted at
`/data`, and a `ClusterIP` Service on port 7860. An Ingress is optional and
must be configured with TLS by the cluster operator. The chart uses the
published CPU image for both amd64 and arm64 nodes; the CUDA Dockerfile is not
supported by this chart.

## Install

```bash
helm upgrade --install shorts-studio ./deploy/helm/shorts-studio \
  --namespace shorts-studio --create-namespace \
  --set-string secretEnv.SHORTS_API_TOKEN='enter-a-token-locally'
```

Keep provider credentials in a Kubernetes Secret or external secret manager;
do not commit them to `values.yaml`. Set `secretEnv.MUAPI_API_KEY`,
`secretEnv.OPENAI_API_KEY`, or `secretEnv.GEMINI_API_KEY` only through a secret
workflow. The default SQLite rate limiter is shared by all workers that mount
the same `/data` volume. For multi-node or multi-replica deployments, place a
gateway rate limiter in front of the Service and use one shared storage class
that provides the required access semantics.

Validate a release before applying it:

```bash
helm lint deploy/helm/shorts-studio
helm template shorts-studio deploy/helm/shorts-studio --set image.tag=0.11.3
```
