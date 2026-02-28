using Gabi.ReliabilityLab.Experiment;

namespace Gabi.ReliabilityLab.Policy;

public interface IEvaluationPolicy
{
    string Name { get; }
    PolicyVerdict Evaluate(ExperimentResult result);
}
