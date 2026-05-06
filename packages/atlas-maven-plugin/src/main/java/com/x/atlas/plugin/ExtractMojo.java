package com.x.atlas.plugin;

import com.x.atlas.plugin.config.AtlasConfig;
import java.io.IOException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.apache.maven.plugin.AbstractMojo;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugin.MojoFailureException;
import org.apache.maven.plugins.annotations.Component;
import org.apache.maven.plugins.annotations.LifecyclePhase;
import org.apache.maven.plugins.annotations.Mojo;
import org.apache.maven.plugins.annotations.Parameter;
import org.apache.maven.plugins.annotations.ResolutionScope;
import org.apache.maven.project.MavenProject;

/**
 * {@code mvn atlas:extract} — runs all configured extractors for the given
 * {@code -Datlas.pair=&lt;id&gt;} (or all pairs in the project when omitted) and
 * writes manifests + coverage manifests to {@code target/atlas/}.
 */
@Mojo(name = "extract",
      defaultPhase = LifecyclePhase.PROCESS_CLASSES,
      requiresDependencyResolution = ResolutionScope.COMPILE,
      threadSafe = true)
public class ExtractMojo extends AbstractMojo {

    @Parameter(defaultValue = "${project}", readonly = true, required = true)
    private MavenProject mavenProject;

    @Parameter(property = "atlas.config", required = true)
    private String configPath;

    @Parameter(property = "atlas.pair")
    private String pairId;

    @Parameter(property = "atlas.repoRoot")
    private String repoRootOverride;

    @Parameter(property = "atlas.failOnUnparseable", defaultValue = "true")
    private boolean failOnUnparseable;

    @Component
    private org.apache.maven.execution.MavenSession session;

    @Override
    public void execute() throws MojoExecutionException, MojoFailureException {
        Path config = Paths.get(configPath).toAbsolutePath().normalize();
        getLog().info("Atlas: loading config " + config);

        AtlasConfig cfg;
        try {
            cfg = AtlasConfig.load(config);
        } catch (IOException e) {
            throw new MojoFailureException("Failed to load atlas.yml: " + e.getMessage(), e);
        }

        Path configDir = config.getParent();
        List<Path> sourceRoots = collectSourceRoots(mavenProject);
        List<Path> classpath = collectClasspath(mavenProject);

        Orchestrator orchestrator = new Orchestrator();
        boolean anyUnparseable = false;
        int pairCount = 0;

        for (AtlasConfig.Project project : cfg.projects) {
            for (AtlasConfig.Repo repo : project.repos) {
                Path declaredRepoRoot = repoRootOverride != null
                        ? Paths.get(repoRootOverride).toAbsolutePath().normalize()
                        : configDir.resolve(repo.path).toAbsolutePath().normalize();
                for (AtlasConfig.DomainPair pair : project.domainPairs) {
                    if (pairId != null && !pairId.equals(pair.id)) continue;
                    pairCount++;
                    getLog().info(String.format("Atlas: extracting %s / %s / %s",
                            project.id, repo.id, pair.id));
                    try {
                        Orchestrator.RunResult r = orchestrator.runPair(
                                project, repo, pair,
                                declaredRepoRoot, sourceRoots, classpath, Map.of());
                        getLog().info(String.format("Atlas: %s edges=%d files=%d mappers=%d",
                                pair.id,
                                r.manifest().stats().edgesEmitted(),
                                r.manifest().stats().filesScanned(),
                                r.manifest().stats().mappersDetected()));
                        anyUnparseable |= r.hasUnparseable();
                    } catch (IOException e) {
                        throw new MojoFailureException("Atlas extract failed: " + e.getMessage(), e);
                    }
                }
            }
        }

        if (pairCount == 0) {
            getLog().warn("Atlas: no pairs matched. Check atlas.yml or -Datlas.pair=<id>");
        }
        if (anyUnparseable && failOnUnparseable) {
            throw new MojoFailureException("Atlas: unparseable files in scope. See coverage manifest.");
        }
    }

    private static List<Path> collectSourceRoots(MavenProject project) {
        List<Path> roots = new ArrayList<>();
        for (Object s : project.getCompileSourceRoots()) {
            roots.add(Paths.get(s.toString()));
        }
        Path generated = project.getBasedir().toPath().resolve("target/generated-sources/annotations");
        if (java.nio.file.Files.exists(generated) && !roots.contains(generated)) {
            roots.add(generated);
        }
        return roots;
    }

    private static List<Path> collectClasspath(MavenProject project) {
        List<Path> cp = new ArrayList<>();
        try {
            for (Object e : project.getCompileClasspathElements()) {
                cp.add(Paths.get(e.toString()));
            }
        } catch (org.apache.maven.artifact.DependencyResolutionRequiredException ignore) {}
        return cp;
    }
}
